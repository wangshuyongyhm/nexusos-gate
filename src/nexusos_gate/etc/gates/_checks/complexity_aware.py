"""检查类型: complexity_aware — 复杂度分级差异化检查(Task489 项1)。

读 task.md frontmatter complexity 字段(L0/L1/L2,缺失默认 L1):
  L0(机械): 放行——五层资产/验证等级要求降级(本插件 pass 不干预)
  L1(标准默认): 放行——现有规则不变(本插件 pass 不干预)
  L2(复杂/高风险): 强制 Level 3 验证标注 + 决策暴露块(缺则 fail)

gate_engine severity 静态限制说明：
  本插件 severity 设 REJECT，但只在 L2 缺要求时返回 fail。
  L0/L1 永远 pass（降级/默认行为不在此插件强制，由其他 G 项自然检查）。
"""
import os
import re
from pathlib import Path

# 工作区根：1959 单3 起不再 parents[N] 推导（audit §1 行13），发现策略单源
# _workspace_root（显式 > env NEXUS_ROOT 布局探测 > git root > None）。
try:
    import _workspace_root
except ImportError:
    from . import _workspace_root


def _auto_dir() -> Path | None:
    """自动化脚本目录（task_state 所在 sys.path 项）；不可得 → None（fail-open）。"""
    root = _workspace_root.resolve_workspace_root()
    if root is None:
        return None
    auto = root / "05-System" / "自动化脚本" if root.name != "自动化脚本" else root
    return auto if auto.is_dir() else None


def _get_task_path(context: dict) -> str:
    """从 context 或 task_state 获取 task.md 路径。"""
    tp = context.get("task_path", "") or ""
    if tp and os.path.exists(tp):
        return tp
    task_id = context.get("task_id", "")
    if task_id:
        try:
            auto = _auto_dir()
            if auto is None:
                return ""
            import sys
            if str(auto) not in sys.path:
                sys.path.insert(0, str(auto))
            from nexusos_xdr import task_state
            s = task_state.load_state(task_id)
            if s:
                return s.get("task_path", "") or ""
        except Exception:
            pass
    return ""


def _read_complexity(task_path: str) -> str:
    """从 task.md frontmatter 读 complexity 字段。默认 L1。"""
    if not task_path or not os.path.exists(task_path):
        return "L1"
    try:
        with open(task_path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
        m = re.search(r'^complexity:\s*(\S+)', text, re.MULTILINE)
        if m:
            val = m.group(1).strip().strip("'\"")
            if val in ("L0", "L1", "L2"):
                return val
    except Exception:
        pass
    return "L1"


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      report_path: report.md 路径(可选,优先用 context.task_path_report)
    context:
      task_path / task_id: 定位 task.md
    返回: (passed, detail)
    """
    task_path = _get_task_path(context)
    report_path = (params.get("report_path", "") or
                   context.get("task_path_report", "") or "")
    complexity = _read_complexity(task_path)

    if complexity == "L0":
        return True, "complexity=L0(机械任务),验证/资产要求降级,本插件放行"

    if complexity == "L1":
        return True, "complexity=L1(标准),默认规则不变,本插件放行"

    # L2: 强制 Level 3 验证标注 + 决策暴露块
    report_text = ""
    if report_path and os.path.exists(report_path):
        try:
            with open(report_path, encoding="utf-8", errors="ignore") as f:
                report_text = f.read()
        except Exception:
            pass

    issues = []
    has_l3 = bool(re.search(r'Level\s*3|L3|端到端|场景验证|真实场景|e2e',
                            report_text, re.IGNORECASE))
    if not has_l3:
        issues.append("缺 Level 3 验证标注(L2 任务强制)")

    has_decision = bool(re.search(r'决策暴露|选择.*替代|decision.*exposure|替代方案',
                                  report_text, re.IGNORECASE))
    if not has_decision:
        issues.append("缺决策暴露块(L2 任务强制)")

    if issues:
        return False, f"complexity=L2(高风险)但: {'; '.join(issues)}"
    return True, "complexity=L2(高风险),Level 3 验证 + 决策暴露块齐全"
