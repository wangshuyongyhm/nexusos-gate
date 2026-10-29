"""检查类型: verification_level_marked — 报告含"完成/闭环"断言时需有验证等级标注。
P9: persist gate WARN 级——08110853 痛点固化（Level 2 冒充 Level 3）。

判定：report/commit_msg 含完成类断言 + 零验证标注 → WARN（不阻塞）。
有标注 或 无断言 → pass。
"""
import re
from pathlib import Path

# 完成类断言关键词
_COMPLETION_PATTERNS = re.compile(
    r"完成|闭环|没问题|全部通过|已修复|已验证",
    re.I,
)

# 验证等级标注模式
_VERIFICATION_PATTERNS = re.compile(
    r"Level\s*[123]|端到端|函数层|场景验证"
    r"|\[verified|verified:|tested:|checked:level"
    r"|smoke\s*test|e2e|端到端验证",
    re.I,
)


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      report_path: report.md 路径
      commit_msg: commit 消息（可选）
    返回: (passed, detail)  # severity WARN，即使 fail 也不阻塞
    """
    report_path = params.get("report_path", "")
    commit_msg = params.get("commit_msg", "") or ""

    # 收集所有文本
    texts = [commit_msg]
    if report_path:
        p = Path(report_path)
        if p.exists():
            try:
                texts.append(p.read_text(encoding="utf-8"))
            except Exception:
                pass

    combined = " ".join(texts)

    # 检查是否有完成类断言
    has_completion = bool(_COMPLETION_PATTERNS.search(combined))
    # 检查是否有验证标注
    has_verification = bool(_VERIFICATION_PATTERNS.search(combined))

    if not has_completion:
        return True, "无完成类断言，跳过验证标注检查"

    if has_verification:
        return True, "✅ 含完成断言且有验证等级标注"

    # 有完成断言但无验证标注 → WARN
    return False, '⚠️ 报告含"完成/闭环"但无验证等级标注（Level 1/2/3、端到端等），请按 VERIFICATION-DISCIPLINE.md 标注'
