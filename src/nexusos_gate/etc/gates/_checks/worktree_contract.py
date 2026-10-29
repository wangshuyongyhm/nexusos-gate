"""检查类型: worktree_contract — dispatch gate D8「代码任务 worktree 契约」（Task 1376）。

机制背景：9 worktree/9 分支漂移两次造成修复丢失（1340/1346、Build43），用户拍板
方案 A（单集成仓+任务级 worktree）。D8 在派发源头强制：含代码改动的任务书必须带
「worktree 契约」段（基线=集成仓 main、nexus-wt start/done 命令行、merge 回 main），
否则 REJECT——机制不靠自觉。

判定：
  1. 任务书不含代码改动关键词（lib/ .dart .py .sh src/）→ 非代码任务，跳过（pass）。
  2. 含代码关键词 → 契约关键词（nexus-wt / 集成仓 main / merge 回 main）任二命中 → pass；
     否则 REJECT（提示补模板段，模板见 task-spec §9）。
"""
import re
from pathlib import Path

_CODE_KW_RE = re.compile(r"lib/|\.dart|\.py|\.sh\b|src/")
_CONTRACT_KWS = ("nexus-wt", "集成仓 main", "merge 回 main")


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无特殊参数)
    context: task_dir（dispatch gate required）
    返回: (passed, detail)
    """
    task_dir = context.get("task_dir", "")
    task_md = str(Path(task_dir) / "input" / "task.md")
    if not Path(task_md).is_file():
        return True, "task.md 不存在（D1 已拦），跳过契约校验"

    try:
        text = Path(task_md).read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        return True, f"task.md 读取失败（放行，D1 兜底）: {e}"

    if not _CODE_KW_RE.search(text):
        return True, "非代码任务（无 lib/.dart/.py/.sh/src 关键词），D8 跳过"

    hits = [k for k in _CONTRACT_KWS if k in text]
    if len(hits) >= 2:
        return True, f"worktree 契约命中 {len(hits)}/3: {hits}"
    return False, (
        "代码任务缺 worktree 契约（命中 "
        f"{len(hits)}/3 {hits}，需 ≥2：nexus-wt / 集成仓 main / merge 回 main）。"
        "补任务书「worktree 契约」段——模板直接抄 task-spec §9"
    )
