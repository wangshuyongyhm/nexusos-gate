"""test_2611172046_b5_inline_strip.py — G11 行内 code span 剥离对抗用例（B5，池#826 邻接）。

三态+边界（任务书 §5.2）：
  态1  行内示例 [[x]] 不再进提取（B3 误报根场景）
  态2  行内外的真 wikilink 仍正常提取
  态3  围栏内 wikilink 行为不变（G14/#826③ 回归）
边界：嵌套双包单（陷阱3）、落单残缺、行内紧邻围栏（陷阱1）、跨行不配（陷阱2）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import _vaultlink as V  # noqa: E402


def extract(text: str):
    return V.extract_wikilinks(text)


def test_inline_example_not_extracted():
    """态1：行内反引号内的示例性 wikilink 不提取（B3 字面场景）"""
    assert extract("库内锚（`[[wikilink]]` 可解析=已验）") == []
    assert extract("示例性写法 `[[nonexistent/fake-page]]` 不应校验") == []
    assert extract("单双皆剥 `[[a]]` 与 ``[[b]]``") == []


def test_real_wikilinks_still_extracted():
    """态2：行内外的真链接照常提取"""
    out = extract("真 [[task/x/input/task|任务书]] 与 `示例 [[fake]]` 后的 [[references]]")
    assert out == ["task/x/input/task", "references"]


def test_fence_behavior_unchanged():
    """态3：围栏内 wikilink 不提取；围栏外真链接提取（#826③ 回归）"""
    text = "前 [[pre-real]]\n```\n[[inside-fence]]\n```\n后 [[post-real]]"
    assert extract(text) == ["pre-real", "post-real"]
    # 行内提及 ```yaml 不是围栏（#826③ 语义保持）
    assert extract("写「尾部加 ```yaml 围栏」再 [[real-after]]") == ["real-after"]


def test_nested_double_wraps_single():
    """陷阱3：CommonMark 双包单——``a `b` [[x]]`` 整体是一个 code span"""
    assert extract("嵌套 ``a `b` [[nested-x]]`` 尾") == []
    assert extract("``[[x]] `y` `` 后") == []


def test_odd_dangling_backtick_kept():
    """落单奇数反引号=语法残缺，按普通文本保持提取（docstring 口径）"""
    out = extract("残缺 `[[odd-backtick]] 和真 [[06-Memory/未决问题池-active]]")
    assert out == ["odd-backtick", "06-Memory/未决问题池-active"]


def test_inline_adjacent_fence():
    """陷阱1：行内跨度后紧跟围栏开栏——先围栏后行内，互不啃食"""
    text = "`[[pre-fence]]`\n```python\n[[fenced]]\n```\n[[after-fence]]"
    assert extract(text) == ["after-fence"]


def test_no_cross_line_pairing():
    """陷阱2：双反引号跨度不跨行（[^\n] 语义）；单反引号跨行=Task1301 有意放宽"""
    text = "开头 `[[unclosed\n接着 [[real-link]]"
    # `[[unclosed 未闭合 ]]>非合法 wikilink 本就不提取；real-link 是真链接
    assert extract(text) == ["real-link"]
    # Task1301 语义保持：单反引号跨行配对合法（code span 渲染为空格）——span 内 wikilink 剥
    text2 = "a `line1\n[[inside-span]]\nline2` b [[real-mid]]"
    assert extract(text2) == ["real-mid"]
    # 双反引号跨行不配（#826③ 宁保留口径）——内部 wikilink 按文本提取
    text3 = "``dup\n[[dup-span]]\ndup`` [[after-dup]]"
    assert "dup-span" in extract(text3) and "after-dup" in extract(text3)
