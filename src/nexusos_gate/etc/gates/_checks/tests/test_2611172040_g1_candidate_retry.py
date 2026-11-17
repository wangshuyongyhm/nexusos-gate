"""test_2611172040_g1_candidate_retry.py — B1b：G1 files_exist 候选重试序补完（池 #858）。

配方真源：MEM#116284/#116285（2611111773 已落地主体）。B1b 补两处缺口并锚定反误伤：
  缺口1：候选序里缺「去首尾空白」形态（files 手抄列表常见残留）；
  缺口2：fail 明细只报原串，排障者会以为文件真缺——必须列全候选序（陷阱3）。
本套同时把任务书验收的四类用例全部锚死：
  ① 带注解后缀的实存路径 pass（中文（）+ 英文 () 两种，陷阱2）
  ② 裸相对路径 pass
  ③ 真缺失 fail 且明细含完整候选序
  ④ 真文件名本身含全角括号/逗号的 pass（反误伤锚定——候选重试序存在的理由）
  ⑤ 首尾带空白的实存路径 pass（B1b 新增能力）
  ⑥ 候选序首项必须是原始串（陷阱1：先剥后试＝预剥离换皮）

运行：python3 -m pytest nexusos_gate/etc/gates/_checks/tests/test_2611172040_g1_candidate_retry.py -v
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import files_exist as fe  # noqa: E402
from files_exist import _candidates_for, check  # noqa: E402

# Vault 内实存文件（conftest 已锚定 NEXUS_VAULT_ROOT；裸跑无 env 时这些断言会红，
# 与既有 test_2611111773_g1_annotation.py 同口径）
_REAL_FILE = "05-System/NEXUS-CONSTRAINT/index.md"


# ── ① 带注解后缀 pass（全角/半角两种括号） ──────────────────────────────
def test_annotated_suffix_passes():
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": [_REAL_FILE + "（done 时 auto-relocate 外迁，见 stzb-assets/迁移区）"]},
        "t",
    )
    assert passed, detail
    assert "候选变形" in detail or "注解" in detail


def test_halfwidth_paren_annotation_passes():
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": [_REAL_FILE + " (relocated at done)"]},
        "t",
    )
    assert passed, detail


# ── ② 裸路径 pass ──────────────────────────────────────────────────────
def test_bare_path_passes():
    passed, detail = check({"jsonpath": "files"}, {"files": [_REAL_FILE]}, "t")
    assert passed, detail
    assert detail == f"全部 1 个文件存在"


# ── ③ 真缺失 fail + 明细含完整候选序（B1b 缺口2） ─────────────────────
def test_missing_reports_candidate_order():
    ghost = "task/000-b1b-nonexistent/output/report.md（外迁备注）"
    passed, detail = check({"jsonpath": "files"}, {"files": [ghost]}, "t")
    assert not passed
    assert "候选重试序" in detail, detail
    # 原串与剥离形都必须出现在明细里（否则排障者只看到"带注解的串"）
    assert "output/report.md" in detail
    assert "试过" in detail


# ── ④ 反误伤锚定：真文件名本身含全角括号/逗号 ──────────────────────────
def test_real_filename_with_fullwidth_parens_and_comma_passes(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        real = os.path.join(td, "report（终稿），v2.md")
        open(real, "w").write("# x")
        passed, detail = check({"jsonpath": "files"}, {"files": [real]}, "t")
        assert passed, detail
        # 相对路径形态：相对基准是 Vault 根（37571 语义不动），把模块级 _VAULT_ROOT
        # 指到临时目录，验「相对串不被剥坏」
        monkeypatch.setattr(fe, "_VAULT_ROOT", td)
        passed_rel, detail_rel = check(
            {"jsonpath": "files"}, {"files": ["report（终稿），v2.md"]}, "t")
        assert passed_rel, detail_rel


# ── ⑤ 首尾空白 pass（B1b 新增候选形态） ───────────────────────────────
def test_whitespace_padded_path_passes():
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": ["  " + _REAL_FILE + "  "]},
        "t",
    )
    assert passed, detail


# ── ⑥ 候选序首项=原始串（陷阱1 锚定） ─────────────────────────────────
def test_candidate_order_original_first():
    raw = "task/x.md（备注）"
    candidates = _candidates_for(raw)
    assert candidates[0] == raw
    # 剥注解形必须在原串之后，且去空白形不能取代原串
    assert "task/x.md" in candidates
    assert candidates.index(raw) == 0
    # 中段括号不剥（真文件名保护）
    assert _candidates_for("task/report（终稿），v2.md") == ["task/report（终稿），v2.md"]
