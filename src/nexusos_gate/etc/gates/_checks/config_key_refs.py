#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_key_refs.py — Task450 L2 核心：配置键全引用扫描。

封装 ripgrep，扫描"字符串字面量/配置键"在所有文件类型（.py/.json/.yaml/.toml/.md/.plist）的引用。
与 D6_IMPACT 互补：D6 用 codegraph 扫代码符号（AST 级，只 .py），D7 用 rg 扫字符串字面量（全文，含配置）。

设计：
  - rg 主路径，fail-open（rg 不可用返 []）
  - category 按扩展名分类（.py=code / .json/.yaml/.toml/.plist=config / .md=doc / 其他=other）
  - scope 限定（避免噪音）：vault/05-System + 用户配置文件（~/.zcode/cli/config.json 等）
  - 排除：node_modules / __pycache__ / .codegraph/ / rollout / .log / .jsonl / agents/（日志/缓存）

Task450 实证：H5 事故场景（oplog_guard 代码改了漏挂 config），scan_key_refs('oplog_guard')
扫出 ~/.zcode/cli/config.json 中的引用，D7_CONFIG check 触发 WARN。
"""
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

# Vault 根解析：单源 _vault_root 助手（1957 起=nexusos-common 哨兵/env，杀 parents[N] 安装形状假设）
try:
    import _vault_root
except ImportError:
    from . import _vault_root
_RG_TIMEOUT = 30  # rg 扫描兜底

# 扩展名 → category 映射
_EXT_CATEGORY = {
    ".py": "code",
    ".ps1": "code",
    ".sh": "code",
    ".json": "config",
    ".yaml": "config",
    ".yml": "config",
    ".toml": "config",
    ".plist": "config",
    ".ini": "config",
    ".md": "doc",
    ".markdown": "doc",
}

# 排除模式（噪音/缓存/日志）
_EXCLUDE_GLOBS = [
    "**/node_modules/**",
    "**/__pycache__/**",
    "**/.codegraph/**",
    "**/rollout/**",
    "**/cli/agents/**",  # zcode 会话历史
    "**/cli/exec/**",    # zcode 执行日志
    "**/cli/log/**",     # zcode 日志
]

# 兜底解析 task.md 时的虚词过滤（与 codegraph_wrapper 一致）
_NON_KEY_WORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "have", "has",
    "are", "was", "were", "will", "would", "should", "must", "shall", "can",
    "true", "false", "none", "null", "task", "todo", "note", "warning", "error",
    "info", "debug", "all", "any", "new", "old", "set", "get", "put", "post",
    "status", "config", "task_id", "target_agent", "session", "agent",
}


def _default_scope(vault_dir: Optional[str] = None, params: Optional[dict] = None) -> list:
    """构造扫描范围（1959 单3 插件化：目标全部可配，杀私人 home 硬编码）。

    优先级：
      params.scope（清单显式给定，最高）
      > NEXUS_AGENT_CFG_DIRS env（冒号分隔绝对路径；OSS/他机指向自己的配置）
      > vault/05-System（vault 可解析时；解析单源 _vault_root→nexusos-common）
    全部不可得 → []（调用方 WARN skip——不再静默扫别人机器的 ~/.hermes 族，
    audit §1 注释级"设计上就扫私人配置"的 OSS 化收口）。
    排除：rollout/agents/log 等日志目录（在 _EXCLUDE_GLOBS）。
    """
    params = params or {}
    explicit = params.get("scope")
    if explicit:
        return [p for p in explicit if p and Path(p).exists()]
    scope: list = []
    vd = vault_dir or _vault_root.vault_root()
    if vd and Path(vd).is_dir():
        scope.append(str(Path(vd) / "05-System"))
    extra = os.environ.get("NEXUS_AGENT_CFG_DIRS")
    if extra:
        scope.extend(p for p in extra.split(":") if p and Path(p).exists())
    return scope


def _categorize(file_path: str) -> str:
    """按扩展名判 category。"""
    ext = Path(file_path).suffix.lower()
    return _EXT_CATEGORY.get(ext, "other")


def _run_rg(pattern: str, scope_paths: list, timeout: int = _RG_TIMEOUT) -> list:
    """ripgrep 递归搜索多个路径，返回 [{file,line,text}, ...]。

    用 -w word-boundary 避免子串误匹配（status 不匹配 status_code）。
    """
    if not shutil.which("rg"):
        return []
    cmd = ["rg", "-n", "--with-filename", "--no-heading", "-w", pattern]
    # 排除噪音
    for g in _EXCLUDE_GLOBS:
        cmd.extend(["-g", f"!{g}"])
    cmd.extend(scope_paths)
    try:
        # errors="replace" 兜底：~/.hermes/scripts 等含 .pyc 二进制，
        # subprocess text=True 默认 utf-8 strict 解码会抛 UnicodeDecodeError
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, check=False, errors="replace")
        if r.returncode not in (0, 1):  # 1=无匹配
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, UnicodeDecodeError):
        return []

    results = []
    for line in r.stdout.splitlines():
        # rg -n --with-filename 格式：path:line:text
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if m:
            results.append({
                "file": m.group(1),
                "line": int(m.group(2)),
                "text": m.group(3),
            })
    return results


def scan_key_refs(key: str, scope: Optional[list] = None, vault_dir: Optional[str] = None) -> list:
    """查 key（如 oplog_guard / PreToolUse / search_cred）在哪些文件的哪些行被引用。

    Args:
        key: 字符串字面量（不限标识符，任意字符串都行）
        scope: 扫描范围（文件/目录清单），None=用 _default_scope
        vault_dir: Vault 根（仅 scope=None 时用）
    Returns:
        [{"file":..., "line":N, "text":..., "category":...}, ...]
        rg 不可用 → 返 []（fail-open）
    """
    if not key:
        return []
    paths = scope if scope is not None else _default_scope(vault_dir)
    raw = _run_rg(key, paths)
    for r in raw:
        r["category"] = _categorize(r["file"])
    return raw


# ============================================================================
# Task450: D7_CONFIG check 函数（挂 dispatch gate）
# ============================================================================

def _extract_keys_from_frontmatter(task_md_text: str) -> list:
    """从 task.md frontmatter 提 impact_keys（与 D6 impact_symbols 区分）。"""
    m = re.search(
        r"^impact_keys:\s*\[([^\]]*)\]",
        task_md_text,
        re.MULTILINE,
    )
    if not m:
        return []
    raw = m.group(1).strip()
    if not raw:
        return []
    items = [x.strip().strip("\"'") for x in raw.split(",")]
    return [x for x in items if x]


def _extract_keys_from_body(task_md_text: str) -> list:
    """兜底：frontmatter 无 impact_keys 时，从正文提 key 候选。

    策略：
      1. 反引号包裹的标识符（同 codegraph_wrapper）
      2. 任务书常出现的 cred_type 字面量：dispatch_cred / search_cred / done_cred / orchestrator_search_cred
      3. hook event 关键词附近：PreToolUse / UserPromptSubmit / PostToolUse / SessionStart / Stop
    过滤虚词（_NON_KEY_WORDS）。
    """
    candidates = set()

    # 1. 反引号包裹的标识符
    for m in re.finditer(r"`([a-z_][a-z0-9_]{2,})`", task_md_text):
        candidates.add(m.group(1))

    # 2. cred_type 字面量
    for k in ("dispatch_cred", "search_cred", "done_cred",
              "orchestrator_search_cred", "verify_credential"):
        if k in task_md_text:
            candidates.add(k)

    # 3. hook event
    for k in ("PreToolUse", "UserPromptSubmit", "PostToolUse", "SessionStart", "Stop"):
        if k in task_md_text:
            candidates.add(k)

    return [k for k in candidates if k not in _NON_KEY_WORDS]


def _task_md_mentions_path(task_md_text: str, file_path: str) -> bool:
    """检查 task.md 是否提及 file_path（与 codegraph_wrapper 同模式，三层匹配）。"""
    if not file_path:
        return False
    if file_path in task_md_text:
        return True
    fname = file_path.rsplit("/", 1)[-1]
    if fname and fname in task_md_text:
        return True
    stem = fname.rsplit(".", 1)[0] if "." in fname else fname
    if stem and len(stem) >= 4 and stem in task_md_text:
        return True
    return False


def check(params: dict, context: dict, agent: str) -> tuple:
    """D7_CONFIG: dispatch 前配置键关联检查（H5 同款"代码改了漏挂 config"防护）。

    流程：
      1. 取 keys（Z 方案）：
         - 优先 {task_dir}/input/task.md frontmatter impact_keys
         - 无 → 从 task.md 正文提取（反引号 + cred_type + hook event）
      2. 对每个 key 调 scan_key_refs
      3. category=config 的引用点（.json/.yaml/.toml/.plist）检查：
         file 在 task.md 正文出现 → covered
         未出现 → uncovered
      4. uncovered 超阈值 → (False, "配置关联点未体现: ...")
      5. fail-open: rg 不可用 / 无 keys / 无 task_dir → (True, "跳过")

    params:
      max_uncovered: 默认 0
      ignore_keys: 跳过的通用键清单
    context:
      task_dir: 任务目录
    """
    max_uncovered = params.get("max_uncovered", 0)
    ignore_keys = set(params.get("ignore_keys", []) or [])

    # 1959 插件化：扫描目标先解析——全不可得 → WARN skip（禁静默扫私人 home）
    scope = _default_scope(params=params)
    if not scope:
        return False, (
            "config_key_refs: 无扫描目标（params.scope / NEXUS_AGENT_CFG_DIRS / "
            "vault 05-System 至少其一；私配置示例见包内 etc/checks/examples/）——WARN skip"
        ), "WARN"

    task_dir = context.get("task_dir", "")
    if not task_dir:
        return True, "无 task_dir，跳过 D7_CONFIG"

    task_md_path = Path(task_dir) / "input" / "task.md"
    if not task_md_path.exists():
        return True, f"task.md 不存在: {task_md_path}，跳过 D7_CONFIG"

    try:
        task_md_text = task_md_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return True, f"task.md 读取失败（跳过）: {e}"

    # 取 keys：frontmatter 优先，正文兜底
    keys = _extract_keys_from_frontmatter(task_md_text)
    keys_source = "frontmatter"
    if not keys:
        keys = _extract_keys_from_body(task_md_text)
        keys_source = "body-fallback"

    keys = [k for k in keys if k not in ignore_keys]

    if not keys:
        return True, "未提取到任何 impact_keys（frontmatter 和正文都无），跳过 D7_CONFIG"

    # rg 可用性检查（fail-open）
    if not shutil.which("rg"):
        return True, "rg 不可用，跳过 D7_CONFIG（fail-open）"

    # 对每个 key 扫配置引用，攒 uncovered（只看 category=config）
    uncovered = []
    keys_with_hits = 0
    for key in keys:
        try:
            refs = scan_key_refs(key, scope=scope)
        except Exception:
            continue
        if not refs:
            continue
        keys_with_hits += 1
        for r in refs:
            if r.get("category") != "config":
                continue  # 只检查 config 类
            if not _task_md_mentions_path(task_md_text, r["file"]):
                uncovered.append({
                    "key": key,
                    "file": r["file"],
                    "line": r["line"],
                    "text": r["text"][:120],
                })

    if keys_with_hits == 0:
        return True, (
            f"D7_CONFIG: 提取到 {len(keys)} 个 keys（{keys_source}）但全部查无结果，跳过"
        )

    if len(uncovered) > max_uncovered:
        preview = uncovered[:5]
        detail_lines = [
            f"D7_CONFIG: {len(uncovered)} 个配置关联点未在任务书体现"
            f"（{len(keys)} keys from {keys_source}, max_uncovered={max_uncovered}）"
        ]
        for u in preview:
            text_snippet = u["text"].strip()[:80]
            detail_lines.append(
                f"  - key={u['key']}, config_file={u['file']}:{u['line']}"
                f"  | {text_snippet}"
            )
        if len(uncovered) > 5:
            detail_lines.append(f"  ...等 {len(uncovered)} 个")
        return False, "\n".join(detail_lines)

    if uncovered:
        return True, (
            f"D7_CONFIG: {len(uncovered)} 个 uncovered 在 max_uncovered={max_uncovered} 内"
            f"（{len(keys)} keys from {keys_source}）"
        )
    return True, (
        f"D7_CONFIG: 全部 {keys_with_hits} 个有 hits 的 keys 的 config 关联点"
        f"都在任务书体现（{len(keys)} keys from {keys_source}）"
    )


if __name__ == "__main__":
    import sys
    test_key = sys.argv[1] if len(sys.argv) > 1 else "oplog_guard"
    print(f"=== scan_key_refs: {test_key} ===")
    refs = scan_key_refs(test_key)
    by_cat = {}
    for r in refs:
        by_cat.setdefault(r["category"], []).append(r)
    for cat in ("config", "code", "doc", "other"):
        items = by_cat.get(cat, [])
        if items:
            print(f"  [{cat}] {len(items)} 个")
            for x in items[:5]:
                print(f"    {x['file']}:{x['line']}")
