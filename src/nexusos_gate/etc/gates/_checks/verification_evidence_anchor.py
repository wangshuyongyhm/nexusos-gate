"""检查类型: verification_evidence_anchor — EADC 核心(Task489 项3)。

Evidence-Anchored Declaration Consistency: Agent 的验证声明必须附外部证据指针。
gate 只认证据不认声明文本。

检查逻辑:
  1. 检测声明的验证等级(L3/L2/L1/unknown)——从 callback evidence 字段或 summary/report 关键词
  2. L3 声明 → evidence_path 必须存在 + 内容含命令输出特征 → 否则 REJECT
  3. L2 声明 → 建议补 evidence(本插件 pass,gate severity WARN 由 YAML 控)
  4. L1 声明 → pass(建议补强)

severity 策略(gate_engine 静态 severity 限制):
  G7 severity=REJECT。插件只在"L3 声明无证据"时返回 fail → REJECT。
  L2/L1/unknown 返回 pass(不触发 REJECT),detail 里给建议。
"""
import os
import re
from pathlib import Path

_AUTO_DIR = Path(__file__).resolve().parents[7]

# 命令输出特征(证明文件含真实执行记录,非空文件)
_OUTPUT_SIGNATURE = re.compile(
    r'\$\s|curl\s|psql\s|python3\s|bash\s|HTTP_CODE|exit=|✅|❌|通过|ok\b|fail\b'
    r'|\d+\s*行|returncode|stdout|stderr',
    re.IGNORECASE
)


# 验证等级关键词（词表不变——只加"否定语境"判据，不动词面，避免 D10 式词法误拦）
_LEVEL_PATTERNS = (
    ("L3", re.compile(r"level\s*3|\bl3\b|端到端|场景验证|真实场景|\be2e\b", re.IGNORECASE)),
    ("L2", re.compile(r"level\s*2|\bl2\b|函数测试|函数签名|import.*验证|inspect", re.IGNORECASE)),
    ("L1", re.compile(r"level\s*1|\bl1\b|py_compile|语法检查|\bpyc\b", re.IGNORECASE)),
)

# 池 #826①：否定/让步框架标记——与等级字样**邻近**（±_NEG_WINDOW 字符内）出现时，
# 该次命中不算"声明完成度"，不触发索证。选邻近窗口而不是整句黑名单，是因为
# 「L3 验证通过（缺口另见遗留）」这类句子里真声明与如实缺口并存，整句黑名单会误放。
_NEGATION_MARKERS = (
    "缺口", "未验证", "未完成", "未做", "未覆盖", "未测", "未跑", "未能", "未达",
    "不可达", "不适用", "无法", "不足", "待补", "尚未", "没有", "不算", "不构成",
    "缺证", "如实", "不冒充", "不能算", "非l3", "非 l3", "非l2", "非 l2",
)
_NEG_WINDOW = 12


def _negated(text: str, start: int, end: int) -> bool:
    """命中点邻近窗口内是否含否定/让步标记（池 #826① 否定语境判据）。"""
    lo = max(0, start - _NEG_WINDOW)
    hi = min(len(text), end + _NEG_WINDOW)
    window = text[lo:hi].lower()
    return any(marker in window for marker in _NEGATION_MARKERS)


def _detect_level(summary: str, report_text: str) -> str:
    """从 summary/report 检测**声明性**验证等级。

    池 #826①：只看"是否存在该等级的非否定命中"——「L3 缺口（如实）」「L3 未验证」
    这类如实声明不得被当成 L3 完成索证（1735 实证误拦）。
    """
    combined = (summary or "") + "\n" + (report_text or "")
    for level, pattern in _LEVEL_PATTERNS:
        for match in pattern.finditer(combined):
            if not _negated(combined, match.start(), match.end()):
                return level
    return "unknown"


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无,全从 context 取)
    context:
      summary: done 回调摘要
      evidence: {level, method, evidence_path}(callback 扩展字段,可选)
      task_path_report: report.md 路径
    返回: (passed, detail)
    """
    summary = context.get("summary", "") or ""
    evidence = context.get("evidence", {})
    if not isinstance(evidence, dict):
        evidence = {}
    report_path = (evidence.get("evidence_path", "") or
                   context.get("task_path_report", "") or "")

    report_text = ""
    if report_path and os.path.exists(report_path):
        try:
            with open(report_path, encoding="utf-8", errors="ignore") as f:
                report_text = f.read()
        except Exception:
            pass

    # 优先用显式 evidence.level,否则从文本检测
    level = evidence.get("level", "") or _detect_level(summary, report_text)

    if level == "L3":
        if not report_path or not os.path.exists(report_path):
            return False, f"EADC: 声明 L3 验证但 evidence_path 不存在({report_path or '空'})"
        if not _OUTPUT_SIGNATURE.search(report_text):
            return False, (f"EADC: L3 evidence_path 存在但内容无命令输出特征"
                           f"({report_path},需含 curl/psql/python3/exit/✅ 等真实执行记录)")
        method = evidence.get("method", "")
        return True, f"EADC: L3 验证证据锚定通过(path={report_path}, method={method or 'auto-detect'})"

    if level == "L2":
        if not report_path or not os.path.exists(report_path):
            return True, "EADC: L2 声明,建议补 evidence_path(本插件 pass,WARN 级建议)"
        return True, f"EADC: L2 验证证据锚定通过(path={report_path})"

    if level == "L1":
        return True, "EADC: L1 声明(py_compile 级),建议补 L2/L3(本插件 pass)"

    # unknown: 无验证等级声明
    return True, "EADC: 未声明验证等级(无 L1/L2/L3 关键词),建议补标注(本插件 pass)"
