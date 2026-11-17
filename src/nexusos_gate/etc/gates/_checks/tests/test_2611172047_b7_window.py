"""test_2611172047_b7_window.py — G12 机读块尾部窗口判定（B7，池#826）。

四对抗用例（任务书 §5.2）：
  ① B5 现成样本（4180 字符，旧法窗口切进 diff 块体）转 pass
  ② 正常短报告 pass
  ③ 机读块在正文中部（距尾 >3000）仍 fail（防放松）
  ④ 自造 >3000 字符前置 diff 块（窗口起点切进围栏体）pass
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import report_schema as RS  # noqa: E402

# B5 现成语料：NEXUS_VAULT_ROOT env 定位（切片 lint 禁裸盘符路径）；
# env 缺失（如 dist 仓隔离环境）→ 内联同构样本兜底，语义等价（>3000 字符
# 前置 diff 块 + 尾部 yaml 机读块）。
_B5_REL = Path("task/2611172046-zcode-b5-g11-inline/output/report.md")
_VAULT = os.environ.get("NEXUS_VAULT_ROOT", "")
B5_REPORT = Path(_VAULT) / _B5_REL if _VAULT else None
B5_AVAILABLE = B5_REPORT is not None and B5_REPORT.is_file()


def _check(text):
    return RS.check({"path": ""}, {}, "oc") if text is None else _check_text(text)


def _check_text(text):
    import tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(text)
        p = f.name
    try:
        return RS.check({"path": p}, {}, "oc")
    finally:
        os.unlink(p)


TAIL_BLOCK = """
```yaml
# NEXUS machine-readable
status: complete
evidence:
  - sample
next_steps: []
```
"""


def test_b5_real_sample_passes():
    """① B5 现成样本（旧法三轮 G12 误报的触发体）；env 缺失时内联同构样本"""
    if B5_AVAILABLE:
        text = B5_REPORT.read_text()
    else:
        text = ("# R\n\n## diff 段\n\n```diff\n" + ("- 旧行内容稍长一些些\n+ 新行内容稍长一些些\n" * 170)
                + "```\n\n## 结论\n\n正文。\n" + TAIL_BLOCK)
    assert len(text) > 3000, "样本须为长报告"
    ok, detail = _check_text(text)
    assert ok, f"B5 样本应 pass：{detail}"


def test_short_report_passes():
    """② 正常短报告（机读块在尾部）"""
    ok, detail = _check_text("# R\n\n正文。\n" + TAIL_BLOCK)
    assert ok, detail


def test_mid_document_block_still_fails():
    """③ 机读块在正文中部（距尾 >3000）仍 fail——窗口语义不放松"""
    pad = "# 正文段落\n\n" + ("填充内容若干字符，用于把机读块推离尾部窗口三千里外。\n\n" * 160)  # >3000 字符垫层
    text = "# R\n\n" + TAIL_BLOCK + "\n" + pad + "# 尾部更多正文\n"
    assert len(text) - text.index("```yaml") > 3000
    ok, _ = _check_text(text)
    assert not ok, "正文中部块必须 fail（防正文示例误命中）"


def test_window_cut_into_fence_body_passes():
    """④ 自造样本：窗口起点切进前置 diff 围栏体——先配对后验位应 pass"""
    head = "# 长 report\n\n## diff 段\n\n```diff\n" + ("- 旧行内容稍长一些\n+ 新行内容也稍长一些\n" * 150) + "```\n\n"
    text = head + "## 结论\n\n正文若干。\n" + TAIL_BLOCK
    assert len(text) > 3000, "样本须超窗口"
    # 窗口起点确实落在 diff 块体内（复现旧法病灶）
    assert text[len(text) - 3000:].count("```") < 6 or True  # 结构性检查见下
    diff_start = text.index("```diff")
    diff_end = text.index("```", diff_start + 7)
    assert diff_start < len(text) - 3000 < diff_end, "窗口起点须切进 diff 块体"
    ok, detail = _check_text(text)
    assert ok, f"窗口切进围栏体应 pass：{detail}"
