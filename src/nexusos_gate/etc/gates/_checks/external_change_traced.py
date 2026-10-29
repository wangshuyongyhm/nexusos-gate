"""检查类型: external_change_traced — 改 Vault 外文件需在 Vault 内留记录。
P8: persist gate 检查 external_changes 中的路径是否在会话日志或 report.md 中有留痕。

Task 483：08110853 痛点固化——改了 ~/.deepseek/config.toml 但 Vault 内无记录。
Task 483-patch1：修复 list 占位符陷阱（gate_engine 传 "[]" 字符串被误判为非空）。
"""
import ast
from pathlib import Path


def _coerce_list(value):
    """把 value 规整成 list[str]。处理 gate_engine 占位符传来的 "[]" 字符串。

    gate_engine 把 {committed_files} 占位符解析成 Python repr 字符串 "[]"，
    而非真正的 list。isinstance(x, str) 分支用 ast.literal_eval 还原。
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(d) for d in value if d]
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            try:
                parsed = ast.literal_eval(s)
                return [str(d) for d in parsed if d] if isinstance(parsed, list) else []
            except Exception:
                return []
        return [s] if s else []
    return [str(value)] if value else []


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      external_changes: list[str]，Vault 外改动文件路径
      session_log_path: 会话日志路径（查留痕）
      report_path: report.md 路径（查留痕）
      committed_files: list[str]，本次 commit 的文件（保守版：非空就过）
    返回: (passed, detail)
    """
    external_changes = _coerce_list(params.get("external_changes", []))
    if not external_changes:
        return True, "✅ 无外部配置变更，无需留痕"

    # 保守版：committed_files 非空就过（有 git commit 含记录）
    committed_files = _coerce_list(params.get("committed_files", []))
    if committed_files:
        return True, f"✅ 有 committed_files({len(committed_files)})，留痕已通过 commit"

    # 查 session_log 和 report 是否含任一 external 路径
    log_path = params.get("session_log_path", "")
    report_path = params.get("report_path", "")

    for search_file in [log_path, report_path]:
        if not search_file:
            continue
        p = Path(search_file)
        if not p.exists():
            continue
        try:
            content = p.read_text(encoding="utf-8")
            for ext_path in external_changes:
                if ext_path in content or Path(ext_path).name in content:
                    return True, f"✅ 外部变更 {ext_path} 在 {p.name} 中有留痕"
        except Exception:
            pass

    return False, f"❌ {len(external_changes)} 个外部变更未留痕: {external_changes[:3]}"
