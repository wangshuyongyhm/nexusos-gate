"""test_2611111773_g1_annotation.py — G1 files_exist 行内注解剥离修复单测（Task 2611111773）。

池 #858（1750 发现）：done 回调 files 带「路径（中文括号注解）」形态时，注解被
吃进路径 → 1550 单 8/8 点名文件实存仍 REJECT。修复契约：
  1. 尾部行内注解（中文（）/英文 () 括号，内容无嵌套）剥离后重试——注解吃进路径
     的真文件必须通过；
  2. 原路径优先——原路径存在时绝不剥离（真文件名尾部含括号的保护）；
  3. 剥离后仍不存在 = 真幽灵，REJECT 语义不动；
  4. 路径中段括号不剥（`report(2).md` 真文件名保护）。

运行：python3 -m pytest nexusos_gate/etc/gates/_checks/tests/test_2611111773_g1_annotation.py -v
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from files_exist import check, _strip_trailing_annotation

VAULT_ROOT = os.environ.get("NEXUS_VAULT_ROOT") or ""

# 1550 复现用的 8 个 Vault 内真实文件（fixture 前置断言必须全实存）
_REAL_FILES = [
    "05-System/NEXUS-CONSTRAINT/index.md",
    "05-System/NEXUS-CONSTRAINT/quickref.md",
    "AGENTS.md",
    "README.md",
    "06-Memory/未决问题池-active.md",
    "05-System/自动化脚本/nexus-integrity-check.py",
    "05-System/自动化脚本/task-output-lint.sh",
    "05-System/自动化脚本/nexus-persist-commit.sh",
]


# ================================================== ① 1550 复现：8/8 带注解真文件
def test_1550_annotated_real_files_pass():
    """① 8 条真实路径+中文括号注解 → 改前 8/8 REJECT，改后全通过。"""
    annotated = [
        f + "（主报告）" for f in _REAL_FILES[:4]
    ] + [
        f + "（证据快照，含机读块）" for f in _REAL_FILES[4:]
    ]
    for f in _REAL_FILES:
        assert os.path.isfile(os.path.join(VAULT_ROOT, f)), f"fixture 前置: {f} 实存"
    passed, detail = check({"jsonpath": "files"}, {"files": annotated}, "t")
    assert passed, detail
    assert "不存在" not in detail


# ================================================== ② 英文括号注解
def test_english_paren_annotation_pass():
    """② 英文括号尾部注解同剥。"""
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": [_REAL_FILES[0] + " (main report)"]}, "t")
    assert passed, detail


# ================================================== ③ 剥离函数语义
def test_strip_trailing_annotation():
    """③ 剥离函数：尾部中文/英文括号剥、中段不动、无注解原样。"""
    assert _strip_trailing_annotation("task/x/output/report.md（主报告）") == "task/x/output/report.md"
    assert _strip_trailing_annotation("task/x/output/report.md (note)") == "task/x/output/report.md"
    assert _strip_trailing_annotation("task/x/output/report.md(带空格内容 混合)") == "task/x/output/report.md"
    assert _strip_trailing_annotation("task/report(2).md") == "task/report(2).md"  # 中段括号不动
    assert _strip_trailing_annotation("task/plain.md") == "task/plain.md"          # 无注解原样
    # 嵌套括号不剥（内容含括号=非注解形态，保守）
    assert _strip_trailing_annotation("task/x.md（a(b)c）") == "task/x.md（a(b)c）"


# ================================================== ④ 真幽灵仍拒（无注解）
def test_ghost_no_annotation_reject():
    """④ 真不存在路径（无注解）→ 仍 REJECT（拦截语义不动）。"""
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": ["task/000-not-exist/output/ghost.md"]}, "t")
    assert not passed, "真幽灵必须 REJECT"
    assert "不存在" in detail


# ================================================== ⑤ 真幽灵仍拒（带注解）
def test_ghost_with_annotation_reject():
    """⑤ 带注解但剥离后仍不存在 → 仍 REJECT（注解不是幽灵免罪符）。"""
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": ["task/000-not-exist/output/ghost.md（这个文件真的没有）"]}, "t")
    assert not passed, "剥离后仍幽灵必须 REJECT"
    assert "不存在" in detail


# ================================================== ⑥ 原路径优先（尾部括号=真文件名）
def test_real_file_with_trailing_parens_protected():
    """⑥ 真文件名尾部含括号且文件实存 → 原路径直接命中，不被剥离误伤。"""
    with tempfile.TemporaryDirectory() as td:
        real = os.path.join(td, "report(2).md")
        open(real, "w").write("# x")
        rel = "report(2).md"
        # 绝对路径直接判定（Task898 三级：绝对路径=文件系统真相）
        passed, detail = check({"jsonpath": "files"}, {"files": [real]}, "t")
        assert passed, detail


# ================================================== ⑦ 混合形态：带注解真文件+真幽灵
def test_mixed_annotated_and_ghost():
    """⑦ 混合数组：注解真文件通过、幽灵计入 missing（报错精准：只列幽灵）。"""
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": [
            _REAL_FILES[0] + "（主报告）",
            "task/000-not-exist/output/ghost.md",
        ]}, "t")
    assert not passed
    assert "1/2" in detail                       # 只 1 个幽灵
    assert "ghost" in detail                     # 报错精准指向幽灵（注解文件不计入 missing）


# ================================================== ⑧ min_len 语义不回归
def test_min_len_still_enforced():
    """⑧ 空数组 min_len 拦截不受剥离逻辑影响。"""
    passed, detail = check({"jsonpath": "files"}, {"files": []}, "t")
    assert not passed
    assert "< 1" in detail or "文件数" in detail
