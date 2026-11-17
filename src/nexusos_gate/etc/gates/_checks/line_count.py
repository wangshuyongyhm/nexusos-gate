"""检查类型: line_count — 文件行数检查。
用于 G4(report.md ≥30 行)。

T670 跨目录重定向（池 #36）：接力/收口单常态是把 report 写进**另一个任务目录**
（663 写 652 的 report、664 写 662 的）——{task_path_report} 按本任务 task_path 推导
必落空，曾误 REJECT「文件不存在」。修复：路径缺失且目标 basename 是 report.md 时，
扫回调 files[] 里实际存在的 report 路径——命中则降 WARN 附定位（三元组返回，
engine 按 T670 协议覆写 severity），不 REJECT；纯幽灵（无处可解析）仍 REJECT。
"""

# Task1597 参数化：vault 根经 env/仓内推导解析，不再硬编码本机路径
try:
    from _vault_root import vault_root
except ImportError:  # 包模式加载（gate_engine 以子包形态 import 时）
    from ._vault_root import vault_root

import os
from pathlib import Path

_VAULT_ROOT = vault_root()


def _resolve(fpath: str) -> Path:
    if os.path.isabs(fpath) or fpath.startswith("~"):
        return Path(fpath).expanduser()
    return Path(_VAULT_ROOT) / fpath


def _find_redirect(context: dict) -> str:
    """在回调 files[] 里找实际存在的 report.md（跨目录重定向目标）。

    最简规则（任务书 §3.1）：basename=report.md 且磁盘存在 → 命中。
    返回实际路径串；未命中返回空串。
    """
    for f in (context.get("files") or []):
        if isinstance(f, str) and f.rstrip("/").endswith("/report.md"):
            if _resolve(f).exists():
                return f
    return ""


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      path: 文件路径(支持 {var} 占位符,engine 已解析)
      min: 最小行数
      max: 最大行数(可选)
    返回: (passed, detail) 或 (passed, detail, severity_override)
      三元组仅跨目录重定向时用（engine T670 协议：降 WARN 不 REJECT）
    """
    path = params.get("path", "")
    min_lines = params.get("min", 0)
    max_lines = params.get("max")
    if not path:
        # Task532 P-g3: 占位符 {task_path_report} 未解析（required:false 字段缺失时
        # engine 渲染成空串/原占位符）——fail-open 跳过而非 REJECT（可选字段缺失不该硬拦）
        return True, "task_path_report 未提供（可选字段），跳过 line_count 检查"
    path = str(Path(path).expanduser())
    if not os.path.exists(path):
        # Task532 P-g3 同源: 未解析占位符（含 '{'）按可选缺失处理
        if "{" in path:
            return True, f"path 占位符未解析（可选字段缺失），跳过: {path[:60]}"
        # T670: 跨目录重定向——接力单 report 写在另一任务目录（663/664/665 实证）
        if path.rstrip("/").endswith("/report.md"):
            actual = _find_redirect(context)
            if actual:
                ap = _resolve(actual)
                try:
                    n = sum(1 for _ in open(ap, encoding="utf-8", errors="ignore"))
                except OSError:
                    n = -1
                line_note = f"{n} 行" if n >= 0 else "不可读"
                if n >= min_lines:
                    return (False,
                            f"跨目录重定向: 原路径不存在，report 实写于 files[] 所列 {actual}（{line_note}≥{min_lines}）——接力/收口单常态，WARN 不 REJECT（T670）",
                            "WARN")
                return (False,
                        f"跨目录重定向: {actual}（{line_note}<{min_lines} 行，质量仍不达标）",
                        "WARN")
        return False, f"文件不存在: {path}"
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            count = sum(1 for _ in f)
    except OSError as e:
        return False, f"读取失败: {path} ({e})"
    if count < min_lines:
        return False, f"{count} 行 < 最小 {min_lines}({path})"
    if max_lines is not None and count > max_lines:
        return False, f"{count} 行 > 最大 {max_lines}({path})"
    return True, f"{count} 行({path})"
