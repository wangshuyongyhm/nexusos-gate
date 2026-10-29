"""检查类型: report_schema — report.md 尾部机读状态块检查（Task597 #48）。

校验 report.md 尾部 fenced yaml 围栏块：
  - 存在性：尾部有 ```yaml 围栏且含 NEXUS machine-readable 标记
  - 合法性：status ∈ {complete, blocked, continue}；
    status=continue/blocked 时 next_steps 必填非空
缺块/不合法 → WARN（Task597 起步 WARN，存量 report 全无块，REJECT 会瘫验收；
验证有效后由主控裁决升级）。
"""
import os
import re
from pathlib import Path

_MARK_RE = re.compile(r"NEXUS\s+machine-readable", re.IGNORECASE)
_FENCE_RE = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
_STATUS_RE = re.compile(r"^\s*status:\s*(\S+)\s*$", re.MULTILINE)
_NEXT_RE = re.compile(r"^\s*next_steps:\s*(\[.*?\]|\S.*)$", re.MULTILINE)
_VALID = {"complete", "blocked", "continue"}


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      path: report.md 路径（{task_path_report} 占位符，engine 已解析）
    返回: (passed, detail) — WARN 级由 yaml severity 控制
    """
    path = params.get("path", "")
    if not path or "{" in path:
        # 同 line_count Task532 P-g3：可选字段缺失 fail-open 跳过
        return True, "task_path_report 未提供（可选字段），跳过 report_schema 检查"
    path = str(Path(path).expanduser())
    if not os.path.exists(path):
        return True, f"report.md 不存在（{path[:60]}），跳过 report_schema 检查"

    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError as e:
        return False, f"读取失败: {path} ({e})"

    # 只看尾部（最后 3000 字符足够容纳状态块，防正文误命中）
    tail = text[-3000:]
    fences = [m for m in _FENCE_RE.finditer(tail) if _MARK_RE.search(m.group(1))]
    if not fences:
        return False, (
            "report.md 尾部缺机读状态块（Task597 #48：尾部加 ```yaml 围栏，"
            "含 status/evidence/next_steps，模板见 task-spec §2 第 6 项）"
        )

    block = fences[-1].group(1)
    m = _STATUS_RE.search(block)
    if not m:
        return False, "机读块缺 status 字段"
    status = m.group(1)
    if status not in _VALID:
        return False, f"机读块 status 非法: {status}（合法: {sorted(_VALID)}）"
    if status in ("blocked", "continue"):
        nm = _NEXT_RE.search(block)
        if not nm or nm.group(1).strip() in ("[]", ""):
            return False, f"status={status} 时 next_steps 必填非空"
    return True, f"机读块合法（status={status}）"
