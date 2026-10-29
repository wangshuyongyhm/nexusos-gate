"""检查类型: step_completeness — 省略谎报对账(Task489 项2)。

执行侧发现的最大盲区: 三层管"声明了什么"不管"没声明什么"。
跳过步骤不报,三层全静默。本插件做输入侧(task.md 步骤) vs 输出侧(report.md 实际)对账。

解析逻辑(简单关键词匹配,不做 NLP):
  1. task.md "完成标准"段提取步骤项(- [ ] / 1. 2. / - 开头)
  2. 每步提取关键词(中文≥2字 / 英文≥3字)
  3. 关键词在 report.md 出现 = 完成,否则 = 省略
"""
import os
import re
from pathlib import Path

_AUTO_DIR = Path(__file__).resolve().parents[7]


def _get_task_path(context: dict) -> str:
    """从 context 或 task_state 获取 task.md 路径。"""
    tp = context.get("task_path", "") or ""
    if tp and os.path.exists(tp):
        return tp
    task_id = context.get("task_id", "")
    if task_id:
        try:
            import sys
            if str(_AUTO_DIR) not in sys.path:
                sys.path.insert(0, str(_AUTO_DIR))
            from nexusos_xdr import task_state
            s = task_state.load_state(task_id)
            if s:
                return s.get("task_path", "") or ""
        except Exception:
            pass
    return ""


def _extract_steps(task_path: str) -> list:
    """从 task.md 提取完成标准段的步骤项。返回 [{"raw":..., "keywords":[...]}, ...]。"""
    if not task_path or not os.path.exists(task_path):
        return []
    try:
        with open(task_path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:
        return []

    # 找步骤段(Task583: NEXUS 任务书是「## 5. 操作要求/## 6. 验收标准」带编号段名,
    # 原只认「## 完成标准」致对账恒跳过——581/583 实测 0 步。扩展段名+容忍编号前缀)
    m = re.search(r'##\s*\d*[.\s、]*(?:完成标准|操作要求|验收标准)(.*?)(?=\n##\s|\Z)',
                  text, re.DOTALL)
    if not m:
        return []
    section = m.group(1)

    steps = []
    for line in section.splitlines():
        line = line.strip()
        # 匹配 "- [ ] xxx" / "1. xxx" / "- xxx"(但不匹配子缩进的 continuation)
        m2 = re.match(r'^(?:-\s*\[\s*\]\s*|\d+\.\s+|-\s+)(.+)', line)
        if not m2:
            continue
        step_text = m2.group(1).strip()
        # 提取关键词: 中文连续字串拆语义 2-gram + 英文 ≥3字整词
        keywords = []
        en_words = []
        for m in re.finditer(r'[\u4e00-\u9fff]{2,}|[a-zA-Z_][a-zA-Z0-9_]{2,}', step_text):
            tok = m.group(0)
            if re.match(r'[\u4e00-\u9fff]', tok):
                keywords.extend(tok[i:i+2] for i in range(len(tok) - 1))
            else:
                keywords.append(tok)
                en_words.append(tok)
        # Task583: 停用表扩充——「验证/检查」类高频动作词跨步骤串扰(第1步的"验证HTTP"
        # 喂给第3步"验证gamma"致漏报省略)。2-gram OR 太宽松,改单强锚点判定:
        # 首个英文标识符(区分度最高: alpha/beta/gamma/check_agent_ver);无英文则
        # 首个非停用 2-gram。宁漏勿滥(fail-open, WARN 级)。
        stop = {"完成", "标准", "整体", "必须", "可验证", "本次", "≥3", "≥2",
                "验证", "检查", "测试", "确认", "输出", "留证", "任务", "步骤", "事项"}
        anchor = next((w for w in en_words if w.lower() not in
                       {"the", "and", "for"}), None)
        if anchor is None:
            anchor = next((k for k in keywords if k not in stop), None)
        if anchor is None:
            continue  # 无显著区分词,不对账该步(宁漏勿滥)
        steps.append({"raw": step_text[:60], "anchor": anchor,
                      "keywords": [k for k in keywords if k not in stop][:6]})
    return steps


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      report_path: report.md 路径(可选)
    context:
      task_path / task_id: 定位 task.md
      task_path_report: report.md 路径
    返回: (passed, detail) — WARN 级(severity 在 YAML 设 WARN)
    """
    task_path = _get_task_path(context)
    report_path = (params.get("report_path", "") or
                   context.get("task_path_report", "") or "")

    steps = _extract_steps(task_path)
    if not steps:
        return True, "task.md 无可解析步骤项(完成标准段为空或格式不匹配),跳过对账"

    report_text = ""
    if report_path and os.path.exists(report_path):
        try:
            with open(report_path, encoding="utf-8", errors="ignore") as f:
                report_text = f.read()
        except Exception:
            pass
    if not report_text:
        return True, f"report.md 不可读({len(steps)} 步待对账),交 G4 处理"

    # Task583: 单强锚点匹配(英文标识符优先,否则非停用 2-gram)——原 2-gram OR
    # 跨步骤串扰漏报省略。锚点未命中 = 疑似省略。
    omitted = []
    for step in steps:
        report_lower = report_text.lower()
        anchor = step["anchor"].lower()
        if anchor and anchor not in report_lower:
            omitted.append(step["raw"])

    if omitted:
        return False, (f"省略谎报对账: {len(omitted)}/{len(steps)} 步骤在 report.md 未体现: "
                       f"{omitted[:3]}")
    return True, f"步骤对账通过: {len(steps)}/{len(steps)} 步骤均在 report.md 体现"
