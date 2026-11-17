"""检查类型: adversarial_review — 对抗式审查（C13 用, WARN）。

thinking-methodology.md §2 的代码强制层：代码改动时提醒做过对抗式审查
（红队思维：找反例/漏洞/边界）。

4 条证据路径（任一满足即 pass，全不满足 → False 但 severity WARN 软提醒）：
  1. 非代码豁免: changed_files 无代码扩展名 → pass（复用 verification_evidence._has_no_code）
  2. commit_msg 标记: 含 [adversarial:...] → pass
  3. verify 文件含对抗式关键词: verify_*.md / adversarial-review.md 内容含"对抗式/反例/边界/失败/逆向"
  4. test 陪跑: changed_files 含 test_*.py / *_test.py（逆向思维产物）
"""
import os
import re

try:
    from verification_evidence import _has_no_code, _coerce_files
except ImportError:
    from .verification_evidence import _has_no_code, _coerce_files

_ADVERSARIAL_MSG = re.compile(r'\[adversarial:.*?\]', re.IGNORECASE)
_VERIFY_KEYWORDS = ('对抗式', '反例', '边界', '失败', '逆向', 'adversarial', 'edge case')


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无, 全从 context 取)
    context:
      changed_files: 改动文件列表
      commit_msg: 提交信息
      project_root: 项目根（读 verify 文件用）
    返回: (passed, detail)
    """
    changed = _coerce_files(context.get("changed_files"), context)
    if not changed:
        return True, "无改动,跳过"

    # 路径1: 非代码豁免
    if _has_no_code(changed):
        return True, "非代码改动,豁免"

    # 路径2: commit_msg 标记
    msg = context.get("commit_msg", "") or ""
    if _ADVERSARIAL_MSG.search(msg):
        return True, "commit_msg 含对抗式审查标记"

    # 路径3: verify 文件含对抗式关键词
    project_root = context.get("project_root", "") or ""
    for f in changed:
        base = os.path.basename(f).lower()
        if base.startswith("verify_") or base.startswith("adversarial") or base.endswith("_verify.md"):
            full = os.path.join(project_root, f) if project_root else f
            try:
                content = open(full, encoding='utf-8').read().lower()
                if any(k in content for k in _VERIFY_KEYWORDS):
                    return True, f"verify 文件 {base} 含对抗式审查内容"
            except Exception:
                pass

    # 路径4: test 陪跑
    for f in changed:
        base = os.path.basename(f).lower()
        if base.startswith("test_") or base.endswith("_test.py"):
            return True, "有 test 陪跑（逆向思维产物）"

    # 全不满足
    return False, (
        "未发现对抗式审查证据。"
        "建议: commit_msg 加 [adversarial:反例1,反例2] 或附 adversarial-review.md 或补 test。"
        "详见 thinking-methodology.md §2"
    )
