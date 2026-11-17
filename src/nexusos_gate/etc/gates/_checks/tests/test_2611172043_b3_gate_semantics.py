"""test_2611172043_b3_gate_semantics.py — gate 语义域三件回归（池 #826①③ + B1a 邻接）。

覆盖：
  ① G7 verification_evidence_anchor：否定语境不索证（三态：真索证 pass / 否定语境 pass /
     无证据 fail），外加"距离远则不否定"的边界（防一刀切放过真声明）。
  ② D6 parent_anchors / D8 worktree_contract：缺 task.md 不再静默 pass；D6 路径锚按
     vault 内路径严格验（不走 basename 兜底），库内锚（[[未决问题池]]）不误判。
  ③ D9 done_ack：消费义务跟 caller 走——他人未 ack 单不拦我方派单；我方未 ack 单照拦；
    无身份（persist P17）退回全量口径。

运行：python3 -m pytest nexusos_gate/etc/gates/_checks/tests/test_2611172043_b3_gate_semantics.py -v
"""
import os
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import done_ack  # noqa: E402
import parent_anchors  # noqa: E402
import verification_evidence_anchor as g7  # noqa: E402
import worktree_contract  # noqa: E402

VAULT_ROOT = os.environ.get("NEXUS_VAULT_ROOT") or ""
# 路径锚必须指向真实存在的 vault 文件（按路径严格验，不走 basename 兜底）
REAL_PATH_ANCHOR = "task/2611172042-zcode-b2-waitcb-prefix/output/report.md"


def _report(tmp_path: Path, text: str) -> str:
    p = tmp_path / "report.md"
    p.write_text(text, encoding="utf-8")
    return str(p)


def _evidence_report(tmp_path: Path) -> str:
    """带真实命令输出的证据文件（G7 L3 正例需要命令特征）。"""
    return _report(tmp_path, "## 复现\n$ bash reproduce.sh\npython3 -m pytest -q\n54 passed\nrc=0\n")


# ══════════════════════════════════════════════════════════════ ① G7 否定语境
def test_g7_negated_l3_gap_does_not_demand_evidence():
    """「L3 缺口（如实）」不得被当成 L3 完成索证（池 #826① 本体）。"""
    passed, detail = g7.check({}, {
        "summary": "B3 完成：L3 缺口（如实），patrol 侧语义未动，属另单范围",
    }, "ds2")
    assert passed, detail
    assert "L3" in detail or "验证等级" in detail or "跳过" in detail or "通过" in detail


def test_g7_negated_variants():
    """同族否定形态：L3 未验证 / 非 L3 / 不可达 都不索证。"""
    for summary in (
        "本单 L3 未验证：e2e 环境缺 C3 清理",
        "结论非 L3，仅 L2 函数级",
        "L3 端到端验证不可达（监控域 C3 未清）",
    ):
        passed, detail = g7.check({}, {"summary": summary}, "ds2")
        assert passed, f"{summary} → {detail}"


def test_g7_positive_l3_with_evidence_passes(tmp_path):
    ev = _evidence_report(tmp_path)
    passed, detail = g7.check({}, {
        "summary": "L3 端到端验证通过",
        "evidence": {"level": "L3", "method": "端到端", "evidence_path": ev},
    }, "ds2")
    assert passed, detail


def test_g7_positive_l3_without_evidence_rejects(tmp_path):
    """真声明 L3 但没有证据锚 → 仍 REJECT（收紧不得放过真欠证）。"""
    passed, detail = g7.check({}, {"summary": "L3 端到端验证通过，全绿"}, "ds2")
    assert not passed
    assert "L3" in detail


def test_g7_far_gap_word_does_not_cancel_claim(tmp_path):
    """边界：缺口字样离 L3 很远（>12 字符）时不得替真声明开脱。"""
    ev = _evidence_report(tmp_path)
    text = "L3 端到端验证全部通过并且已归档；另有历史遗留的缺口清单放在附录最后一段里供参考"
    passed_with, _ = g7.check({}, {
        "summary": text, "evidence": {"level": "L3", "evidence_path": ev}}, "ds2")
    passed_without, detail_without = g7.check({}, {"summary": text}, "ds2")
    assert passed_with
    assert not passed_without, f"真声明应仍索证，实得: {detail_without}"


# ══════════════════════════════════════════════════════════════ ② D6 路径锚/缺文件
def _task_dir(tmp_path: Path, anchors_line: str, code: bool = False) -> str:
    tdir = tmp_path / "task" / "9999-b3-demo"
    (tdir / "input").mkdir(parents=True, exist_ok=True)
    body = "# demo 任务书\n\n"
    if code:
        body += "改动：scripts/demo.sh 与 gate 包 .py\n\n"
    body += f"parent_anchors: {anchors_line}\n"
    (tdir / "input" / "task.md").write_text(body, encoding="utf-8")
    return str(tdir)


def test_d6_missing_task_md_is_not_silent_pass(tmp_path):
    """缺 task.md → 不再 pass（B1a 实测的假绿形态）。"""
    tdir = tmp_path / "task" / "0000-missing"
    (tdir / "input").mkdir(parents=True)
    passed, detail = parent_anchors.check({}, {"task_dir": str(tdir)}, "ds2")
    assert not passed
    assert "不存在" in detail


def test_d6_path_anchor_existing_passes(tmp_path):
    tdir = _task_dir(tmp_path, f"[[{REAL_PATH_ANCHOR}]]")
    passed, detail = parent_anchors.check({}, {"task_dir": tdir}, "ds2")
    assert passed, detail


def test_d6_path_anchor_missing_fails_without_basename_fallback(tmp_path):
    """路径锚指向的文件不存在 → fail（即使 vault 别处有同名 report.md 也不许兜底）。"""
    ghost = "task/0000-b3-ghost/output/report.md"
    tdir = _task_dir(tmp_path, f"[[{ghost}]]")
    passed, detail = parent_anchors.check({}, {"task_dir": tdir}, "ds2")
    assert not passed
    assert "路径锚目标文件不存在" in detail


def test_d6_wiki_anchor_resolves(tmp_path):
    """库内锚（池行）走 basename 解析——不能被路径锚规则误伤。"""
    tdir = _task_dir(tmp_path, "[[未决问题池]] #826")
    passed, detail = parent_anchors.check({}, {"task_dir": tdir}, "ds2")
    assert passed, detail


def test_d6_missing_wiki_anchor_fails(tmp_path):
    tdir = _task_dir(tmp_path, "[[这个笔记在库里绝对不存在-zzz]]")
    passed, detail = parent_anchors.check({}, {"task_dir": tdir}, "ds2")
    assert not passed
    assert "库内锚无法解析" in detail


# ══════════════════════════════════════════════════════════════ ② D8 契约/缺文件
def test_d8_contract_present_passes(tmp_path):
    tdir = _task_dir(tmp_path, "[[未决问题池]] #826", code=True)
    passed, detail = worktree_contract.check({}, {"task_dir": tdir}, "ds2")
    assert not passed or "命中" in detail  # 本用例任务书没有契约段 → 应 fail
    assert not passed and "缺 worktree 契约" in detail


def test_d8_contract_keywords_two_hits_pass(tmp_path):
    tdir = tmp_path / "task" / "9999-b3-demo2"
    (tdir / "input").mkdir(parents=True)
    (tdir / "input" / "task.md").write_text(
        "# demo\n\n改动 scripts/x.sh\n\n## worktree 契约\n- 基线 = 集成仓 main\n"
        "- nexus-wt start <task_id>\n", encoding="utf-8")
    passed, detail = worktree_contract.check({}, {"task_dir": str(tdir)}, "ds2")
    assert passed, detail


def test_d8_missing_task_md_is_not_silent_pass(tmp_path):
    tdir = tmp_path / "task" / "0001-missing"
    (tdir / "input").mkdir(parents=True)
    passed, detail = worktree_contract.check({}, {"task_dir": str(tdir)}, "ds2")
    assert not passed
    assert "不存在" in detail


# ══════════════════════════════════════════════════════════════ ③ D9 caller 过滤
def _install_fake_task_state(monkeypatch, unacked):
    fake = types.ModuleType("nexusos_xdr.task_state")
    fake.list_unacked = lambda hours=24: list(unacked)
    pkg = types.ModuleType("nexusos_xdr")
    pkg.task_state = fake
    monkeypatch.setitem(sys.modules, "nexusos_xdr", pkg)
    monkeypatch.setitem(sys.modules, "nexusos_xdr.task_state", fake)


def test_d9_other_callers_unacked_do_not_block(monkeypatch):
    """他人派发的未 ack 单不拦我方派单（池 #826③ 本体）。"""
    _install_fake_task_state(monkeypatch, [
        {"task_id": "xdr-other-1", "caller": "zcode", "callee": "ds2", "finished": "2026-11-17T14:00:00"},
    ])
    passed, detail = done_ack.check({"window_hours": 24}, {"agent": "ds2", "caller": "ds2"}, "ds2")
    assert passed, detail
    assert "其他派单方" in detail


def test_d9_own_unacked_still_blocks(monkeypatch):
    _install_fake_task_state(monkeypatch, [
        {"task_id": "xdr-mine-1", "caller": "zcode", "callee": "ds2", "finished": "2026-11-17T14:00:00"},
        {"task_id": "xdr-mine-2", "caller": "ds2", "callee": "ds2", "finished": "2026-11-17T14:05:00"},
    ])
    passed, detail = done_ack.check({"window_hours": 24}, {"agent": "ds2", "caller": "ds2"}, "ds2")
    assert not passed
    assert "xdr-mine-2" in detail
    assert "xdr-mine-1" not in detail


def test_d9_no_identity_keeps_full_scope(monkeypatch):
    """persist P17 场景（无 caller/agent）→ 沿用全量口径，不因过滤变成永不告警。"""
    _install_fake_task_state(monkeypatch, [
        {"task_id": "xdr-other-1", "caller": "zcode", "callee": "ds2", "finished": "2026-11-17T14:00:00"},
    ])
    passed, detail = done_ack.check({"window_hours": 24}, {}, "")
    assert not passed
    assert "xdr-other-1" in detail


def test_d9_all_acked_passes(monkeypatch):
    _install_fake_task_state(monkeypatch, [])
    passed, detail = done_ack.check({"window_hours": 24}, {"agent": "ds2", "caller": "ds2"}, "ds2")
    assert passed
    assert "全部 ack" in detail
