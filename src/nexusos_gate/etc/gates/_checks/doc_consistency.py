"""检查类型: doc_consistency — md 文档一致性验证。

C9 用。当 changed_files 含 .md 时,提取 md 内容里的 NEXUS 相关引用,
验证实际存在(路径/端口/脚本/wikilink)。不一致 = WARN(提醒不硬拦)。

md 是活标准不是豁免品,改 md = 改标准,必须验证描述和实现一致。
"""

# Task1597 参数化：vault 根经 env/仓内推导解析，不再硬编码本机路径
try:
    from _vault_root import vault_root
except ImportError:  # 包模式加载（gate_engine 以子包形态 import 时）
    from ._vault_root import vault_root

import os
import re
from pathlib import Path

# NEXUS 合法端口(只认这些,其他 :NNNN 不检查)
# 19900: nexus_console.server 控制台端口（PID 实证监听；池#269③——gates README
#        历史更新记录行引用它曾触发 C9 误报，1657 补入）
_NEXUS_PORTS = {"11436", "11438", "11537", "19900", "19998", "4001"}

# Agent 启动脚本根（C9 校验文档引用用）。私有 Agent 目录缺省保留（live 行为不变），
# OSS/他机可经 env 指向自己的脚本目录。
_AGENT_SCRIPTS_ROOT = os.environ.get("NEXUS_AGENT_SCRIPTS_ROOT") or "~/.hermes/scripts"

# NEXUS 关键脚本/文件(验证在预期位置存在)
# 格式: (文件名, 候选根目录列表)
_KEY_SCRIPTS = {
    "start_tool.sh": [_AGENT_SCRIPTS_ROOT, None],  # None=全局搜索
    "gate_engine.py": ["05-System/自动化脚本/nexusos_xdr", None],
    "check_agent_versions.sh": ["05-System/自动化脚本", None],
    "nexus-monitor.sh": ["05-System/自动化脚本/nexus-monitor", None],
}


def _coerce_files(value, context: dict) -> list:
    """规整成 list[str]。处理 engine 把 list 占位符转 str 的情况。
    与 file_size.py 的 _coerce_files 同逻辑(ast.literal_eval 解 list repr)。
    """
    import ast
    if value is None:
        v = context.get("changed_files") or []
    else:
        v = value
    if isinstance(v, list):
        return [str(x) for x in v if x]
    if isinstance(v, str):
        s = v.strip()
        if not s or "{" in s:
            cv = context.get("changed_files") or []
            return [str(x) for x in cv if x] if isinstance(cv, list) else []
        if s.startswith("[") and s.endswith("]"):
            try:
                p = ast.literal_eval(s)
                if isinstance(p, list):
                    return [str(x) for x in p if x]
            except Exception:
                pass
            inner = s.strip("[]").strip()
            if not inner:
                return []
            return [x.strip().strip("'\"") for x in inner.split(",") if x.strip()]
        if "," in s:
            return [x.strip() for x in s.split(",") if x.strip()]
        return [s]
    return [str(v)] if v else []


def _strip_code_blocks(text: str) -> str:
    """剥除围栏代码块(```/~~~)和行内代码(`...`),只保留散文区域。

    与 scan_vault_wikilinks 的 strip_code 同逻辑。
    """
    FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
    # 行内代码: CommonMark 等长闭合——N 个反引号开须等长闭合,旧版 `[^`\n]*`
    # 把 ``[[x]]`` 拆成两对空代码致 wikilink 暴露误报断链(未决#27,同 I2 修法)
    INLINE_RE = re.compile(r"(`+)[^`]*\1")
    out_lines = []
    in_fence = False
    fence_marker = None
    for line in text.splitlines():
        if in_fence:
            m = FENCE_RE.match(line)
            if m and m.group(1)[0] == fence_marker:
                in_fence = False
                fence_marker = None
            continue  # 围栏内跳过
        m = FENCE_RE.match(line)
        if m:
            in_fence = True
            fence_marker = m.group(1)[0]
            continue
        # 行内代码替换为空格(保留位置)
        line = INLINE_RE.sub(lambda mm: " " * len(mm.group(0)), line)
        out_lines.append(line)
    return "\n".join(out_lines)


def _check_path_refs(text: str, project_root: str, issues: list) -> None:
    """检查散文中的路径引用(05-System/.../*.py, ~/.hermes/.../*.sh)。"""
    # 匹配 05-System/ 开头的路径 + ~/.hermes/ 路径
    path_re = re.compile(
        r"(?:05-System/[^\s`'\"<>|]+?\.(?:py|sh|yaml|yml|md))"
        r"|(?:~/\.hermes/[^\s`'\"<>|]+?\.(?:sh|py))"
    )
    for m in path_re.finditer(text):
        ref = m.group(0).rstrip(").,;:")
        # 展开 ~ 和 project_root
        if ref.startswith("~/"):
            full = os.path.expanduser(ref)
        elif ref.startswith("05-System/"):
            full = os.path.join(project_root, ref) if project_root else ref
        else:
            continue
        if not os.path.exists(full):
            # 只报前60字符避免超长
            issues.append(f"路径引用不存在: {ref[:60]}")


def _check_port_refs(text: str, issues: list) -> None:
    """检查散文中的 NEXUS 端口引用(只认5个合法端口)。"""
    port_re = re.compile(r":(\d{4,5})")
    for m in port_re.finditer(text):
        port = m.group(1)
        if port in _NEXUS_PORTS:
            continue  # 合法 NEXUS 端口
        # 不是 NEXUS 端口但格式像端口引用(:NNNN) → 提醒
        issues.append(f"端口引用非NEXUS端口: :{port}(合法: {','.join(sorted(_NEXUS_PORTS))})")


def _check_script_refs(text: str, project_root: str, issues: list) -> None:
    """检查关键脚本/命令引用是否存在。"""
    for script_name, candidate_dirs in _KEY_SCRIPTS.items():
        # 只在文本中实际提到时才检查(避免无谓文件系统操作)
        if script_name not in text:
            continue
        found = False
        for d in candidate_dirs:
            if d is None:
                # 全局搜索(project_root 下 maxdepth 3)
                search_root = project_root or "."
                for root, dirs, files in os.walk(search_root):
                    dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__" and x != "node_modules"]
                    # 限制深度
                    depth = root[len(search_root):].count(os.sep)
                    if depth >= 3:
                        dirs[:] = []
                        continue
                    if script_name in files:
                        found = True
                        break
                if found:
                    break
            else:
                d_expanded = os.path.expanduser(d) if d.startswith("~") else os.path.join(project_root or "", d)
                if os.path.exists(os.path.join(d_expanded, script_name)):
                    found = True
                    break
        if not found:
            issues.append(f"脚本引用未找到: {script_name}")


def _check_wikilink_refs(text: str, project_root: str, issues: list) -> None:
    """检查 [[wikilink]] 引用的文件在 vault 中存在(basename 匹配)。"""
    wiki_re = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
    # 合法 target: 排除伪 wikilink(代码变量 [[True]] [[0,0]] 等)
    valid_target = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff\s/.]+$")
    for m in wiki_re.finditer(text):
        target = m.group(1).strip().replace(".md", "")
        if not valid_target.match(target):
            continue
        if target.endswith("/"):
            continue
        # basename 匹配: 在 vault 里找 {target}.md
        short = target.rsplit("/", 1)[-1]
        vault = project_root or "."
        # 只搜 2 层深度(性能)
        found = False
        for root, dirs, files in os.walk(vault):
            dirs[:] = [x for x in dirs if not x.startswith(".") and x != "__pycache__" and x != "node_modules"]
            depth = root[len(vault):].count(os.sep)
            if depth >= 4:
                dirs[:] = []
                continue
            if f"{short}.md" in files:
                found = True
                break
            if f"{target}.md" in files:
                found = True
                break
        if not found:
            issues.append(f"wikilink 断链: [[{target}]]")


def check(params: dict, context: dict, agent: str) -> tuple:
    """C9: md 文档一致性验证。

    Returns:
        (passed: bool, detail: str) — passed=True(软WARN不拦),
        detail 含不一致项列表(gate_engine 根据 severity=WARN 自动归类)。
    """
    files = _coerce_files(params.get("files"), context)
    project_root = (params.get("project_root") or context.get("project_root") or "").strip()
    if isinstance(project_root, str) and "{" in project_root:
        project_root = context.get("project_root", "").strip()

    # 只检查 .md 文件
    md_files = [f for f in files if f.endswith(".md")]
    if not md_files:
        return True, "无 md 改动,跳过文档一致性检查"

    # project_root 默认值(vault 根)
    if not project_root:
        project_root = vault_root()

    all_issues = []
    files_checked = 0

    for md_file in md_files:
        # 读 md 内容(支持相对/绝对/带~路径)
        p = Path(md_file).expanduser()
        if not p.is_absolute() and project_root:
            p = Path(project_root) / md_file
        if not p.exists():
            continue  # 文件不存在可能是已删,不报
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files_checked += 1

        # 剥代码块后检查
        prose = _strip_code_blocks(content)
        file_issues = []
        _check_path_refs(prose, project_root, file_issues)
        _check_port_refs(prose, file_issues)
        _check_script_refs(prose, project_root, file_issues)
        _check_wikilink_refs(prose, project_root, file_issues)

        if file_issues:
            # 去重 + 限制每文件最多报5个(防刷屏)
            seen = set()
            unique = []
            for iss in file_issues:
                if iss not in seen:
                    seen.add(iss)
                    unique.append(iss)
            for iss in unique[:5]:
                all_issues.append(f"{p.name}: {iss}")

    if not all_issues:
        return True, f"文档一致性通过(检查 {files_checked} 个 md,引用均存在)"

    # 有不一致 = WARN(passed=False, 但 severity=WARN 不硬拦)
    return False, f"文档不一致({len(all_issues)} 项): " + "; ".join(all_issues[:3])
