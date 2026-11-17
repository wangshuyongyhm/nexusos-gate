"""检查类型: workspace_residue — persist 场景 P13(Task901)。

commit 后工作区残量检查(#64742 08271547 落盘缺口——touched 暂存漏收 33 任务,
根因无 commit 后残量检查):
  git status --porcelain 非空且含白名单外路径 → 未通过(WARN 级,提示残量)。

参数:
  whitelist: 运行时产物 glob 白名单(可配置,literal scalar 传入)。匹配规则:
     fnmatch 全路径命中,或 pattern 以 / 结尾时按前缀匹配其后代
  cwd: 备用工作目录(context.vault_root 优先)
排除(不计残量):
  - context.touched_dirs 前缀命中的路径(= 本次 commit 范围,gate 跑在 commit 前)
  - 白名单命中路径(运行时产物,如 LOOP checkpoint / vault-health.json / 06-Memory/index.md)
fail-open: 非 git 仓 / vault_root 缺失 / git 命令失败 → pass + 说明(残量检查不阻塞落盘)。
"""
import fnmatch
import os
import subprocess
from pathlib import Path

_DETAIL_MAX = 10  # detail 最多列出的残量条数


def _decode_git_path(raw: str) -> str:
    """porcelain v1 引号路径(C-style 八进制转义)解码;未加引号原样返回。
    八进制序列是路径的 UTF-8 字节流——先组装 bytes 再按 UTF-8 解码
    (逐字节 chr() 会产出 latin-1 乱码,与 fnmatch 白名单 UTF-8 匹配失败)。
    """
    if not (raw.startswith('"') and raw.endswith('"')):
        return raw
    body = raw[1:-1]
    out = []
    i = 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            nxt = body[i + 1:i + 4]
            if len(nxt) == 3 and all(ch in "01234567" for ch in nxt):
                out.append(int(nxt, 8))
                i += 4
                continue
            i += 1
            if i < len(body):
                out.append(ord(body[i]))
        else:
            out.append(ord(c))
        i += 1
    return bytes(out).decode("utf-8", errors="replace")


def _porcelain_paths(vault_root: Path) -> list:
    """工作区变更路径全量(含 untracked 文件级展开)。git 失败抛 RuntimeError。"""
    r = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, cwd=str(vault_root), timeout=15,
    )
    if r.returncode != 0:
        raise RuntimeError(f"git status rc={r.returncode}: {(r.stderr or '').strip()[:120]}")
    paths = []
    for line in r.stdout.splitlines():
        if len(line) < 4:
            continue
        body = line[3:]  # XY + 空格 = 3 字符前缀
        if " -> " in body:
            body = body.split(" -> ", 1)[-1]  # 重命名取新路径
        body = _decode_git_path(body.strip())
        if body:
            paths.append(body)
    return paths


def _whitelisted(path: str, patterns: list) -> bool:
    for p in patterns or []:
        p = p.strip()
        if not p:
            continue
        if fnmatch.fnmatch(path, p):
            return True
        if p.endswith("/") and path.startswith(p):
            return True
    return False


def _touched(path: str, touched_dirs: list) -> bool:
    for t in touched_dirs or []:
        t = str(t).strip().rstrip("/")
        if not t:
            continue
        if path == t or path.startswith(t + "/"):
            return True
    return False


def check(params: dict, context: dict, agent: str) -> tuple:
    whitelist = params.get("whitelist") or []
    vault_root = context.get("vault_root") or params.get("cwd") or os.environ.get("NEXUS_ROOT")
    if not vault_root or "{" in str(vault_root):
        return True, "vault_root 不可解析——跳过残量检查(fail-open)"
    vr = Path(vault_root)
    if not (vr / ".git").exists():
        return True, f"非 git 工作区({vr})——跳过残量检查(fail-open)"
    try:
        paths = _porcelain_paths(vr)
    except Exception as e:
        return True, f"git status 失败——跳过残量检查(fail-open): {e}"
    residue = [p for p in paths
               if not _touched(p, context.get("touched_dirs"))
               and not _whitelisted(p, whitelist)]
    if not residue:
        total = len(paths)
        return True, f"工作区无白名单外残量(总变更 {total} 条,全部在 commit 范围或白名单内)"
    shown = residue[:_DETAIL_MAX]
    more = f" 等{len(residue)}条" if len(residue) > _DETAIL_MAX else ""
    return False, f"工作区残量 {len(residue)} 条(白名单外,commit 后遗留?): {', '.join(shown)}{more}"
