#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_oss_checks.py — 1959 单3：五私人 check OSS 化 + nexusos.gate.checks 协议单测。

覆盖（完成标准 2/3 条）：
  - entry_points 协议：demo check 注入（monkeypatch importlib.metadata）+ 稳定序
  - checks.d 声明式启用：$NEXUS_HOME/gate/checks.d/*.yaml 追加场景 items
  - 五 check 两态：vault 在（=私机等价）/ vault 缺（=干净环境 WARN/skip，不炸）
"""
import importlib
import importlib.metadata
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _workspace_root import resolve_workspace_root  # noqa: E402


# ── _workspace_root 发现策略 ────────────────────────────────

def test_wsroot_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_VAULT_ROOT", "/definitely/not/here")
    assert resolve_workspace_root(str(tmp_path)) == tmp_path


def test_wsroot_env_direct(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_CODEGRAPH_PROJECT", str(tmp_path))
    assert resolve_workspace_root() == tmp_path


def test_wsroot_none_in_clean_env(tmp_path, monkeypatch):
    """干净环境（无 env 无 git）→ None（fail-open 由调用方兜）。"""
    for var in ("NEXUS_CODEGRAPH_PROJECT", "NEXUS_VAULT_ROOT"):
        monkeypatch.delenv(var, raising=False)
    assert resolve_workspace_root(start=tmp_path) is None


def test_wsroot_git_root(tmp_path, monkeypatch):
    for var in ("NEXUS_CODEGRAPH_PROJECT", "NEXUS_VAULT_ROOT"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".git").mkdir()
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert resolve_workspace_root(start=deep) == tmp_path


# ── 五 check 两态 ──────────────────────────────────────────

def _load(name):
    return importlib.import_module(f"nexusos_gate.etc.gates._checks.{name}")


def test_config_key_refs_no_scope_warn_skips(tmp_path, monkeypatch):
    """vault 缺 + 无 scope/env → (False, …, WARN)：不扫私人 home，不 REJECT。"""
    monkeypatch.delenv("NEXUS_VAULT_ROOT", raising=False)
    monkeypatch.delenv("NEXUS_AGENT_CFG_DIRS", raising=False)
    mod = _load("config_key_refs")
    monkeypatch.setattr(mod._vault_root, "vault_root", lambda: "")  # 锚定模块实际持有的对象
    ret = mod.check({}, {"task_dir": str(tmp_path)}, "t")
    assert len(ret) == 3 and ret[2] == "WARN" and not ret[0]


def test_config_key_refs_scope_param(monkeypatch, tmp_path):
    """params.scope 显式给定 → 用之（声明式目标，私人面不硬编码）。"""
    mod = _load("config_key_refs")
    scope = mod._default_scope(params={"scope": [str(tmp_path)]})
    assert scope == [str(tmp_path)]


def test_e2e_suite_evidence_no_cfg_warn_skips(monkeypatch, tmp_path):
    """无 e2e-paths 配置（NEXUS_HOME 指空沙箱）→ 3 元组 WARN skip 非 fail。"""
    monkeypatch.setenv("NEXUS_HOME", str(tmp_path / "no-home"))
    monkeypatch.delenv("NEXUS_GATE_E2E_PATHS", raising=False)
    mod = _load("e2e_suite_evidence")
    ret = mod.check({}, {}, "t")
    assert len(ret) == 3 and ret[2] == "WARN" and not ret[0]


def test_e2e_suite_evidence_cfg_from_home(monkeypatch, tmp_path):
    """$NEXUS_HOME/gate/e2e-paths.yaml 在场 → 正常判定路径（含占位展开）。"""
    home = tmp_path / "nx-home"
    (home / "gate").mkdir(parents=True)
    (home / "gate" / "e2e-paths.yaml").write_text(
        "suite_entry: ${NEXUS_VAULT_ROOT}/e2e/run.sh\n"
        "system_path_patterns:\n  - src/**\n"
        "read_only_markers: []\n"
        "task_md_system_markers: []\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXUS_HOME", str(home))
    monkeypatch.delenv("NEXUS_GATE_E2E_PATHS", raising=False)
    monkeypatch.setenv("NEXUS_VAULT_ROOT", str(tmp_path))
    mod = _load("e2e_suite_evidence")
    cfg = mod._load_cfg({"vault_root": str(tmp_path)})
    assert cfg["suite_entry"] == f"{tmp_path}/e2e/run.sh"
    # 非系统改动单（files 未命中 patterns）→ 豁免 pass
    ret = mod.check({}, {"files": ["docs/x.md"], "vault_root": str(tmp_path)}, "t")
    ok, detail = ret[0], ret[1]
    assert ok and "非系统改动单" in detail


def test_persist_pool_ledger_missing_script_warn_skips(monkeypatch, tmp_path):
    """vault 在但取号脚本缺 → WARN skip（sync/check 同口径 fail-open）。"""
    monkeypatch.setenv("NEXUS_VAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("NEXUS_POOL_NEXT_ID_SCRIPT", raising=False)
    from nexusos_gate import persist_pool_ledger as ppl
    ret = ppl.check({}, {"vault_root": str(tmp_path)}, "t")
    assert len(ret) == 3 and ret[2] == "WARN"
    sync = ppl.sync({"vault_root": str(tmp_path)}, {"failures": []}, agent="t")
    assert sync.get("skip")


def test_codegraph_wrapper_clean_env_fail_open(monkeypatch, tmp_path):
    """干净环境（无根可发现）→ scan 返 []（fail-open 保留）。"""
    for var in ("NEXUS_CODEGRAPH_PROJECT", "NEXUS_VAULT_ROOT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    mod = _load("codegraph_wrapper")
    assert mod.scan_symbol_impact("nope") == []


def test_complexity_aware_clean_env_defaults():
    """干净环境 task_state 不可得 → complexity 默认 L1（fail-open）。"""
    mod = _load("complexity_aware")
    assert mod._read_complexity("") == "L1"


def test_doc_consistency_importable_clean(monkeypatch, tmp_path):
    """doc_consistency 干净环境可 import + check 可调（无 vault 不炸）。"""
    monkeypatch.delenv("NEXUS_VAULT_ROOT", raising=False)
    mod = _load("doc_consistency")
    assert callable(mod.check)


# ── entry_points 协议 ──────────────────────────────────────

def test_entry_points_demo_injection(monkeypatch):
    """协议可用性：monkeypatch entry_points 注入 demo check → 引擎加载可用。"""
    from nexusos_gate import gate_engine

    class _DemoEP:
        name = "aaa_demo_check"
        value = "tests_demo_module"

        def load(self):
            def _check(params, context, agent):
                return True, f"demo ok:{params.get('k','')}"
            return _check

    class _DemoEP2:
        name = "zzz_demo_check"
        value = "tests_demo_module2"

        def load(self):
            def _check(params, context, agent):
                return True, "demo2"
            return _check

    monkeypatch.setattr(
        importlib.metadata, "entry_points",
        lambda group=None: [_DemoEP(), _DemoEP2()] if group == "nexusos.gate.checks" else [],
    )
    loaded = gate_engine._load_entry_point_checks()
    assert list(loaded) == ["aaa_demo_check", "zzz_demo_check"]  # sorted 稳定序（陷阱1）
    assert loaded["aaa_demo_check"]({"k": "v"}, {}, "t") == (True, "demo ok:v")


def test_checks_d_user_enablement(monkeypatch, tmp_path):
    """checks.d 声明式启用：$NEXUS_HOME/gate/checks.d/*.yaml items 追加进场景。"""
    home = tmp_path / "nxhome"
    d = home / "gate" / "checks.d"
    d.mkdir(parents=True)
    (d / "z-extra.yaml").write_text(
        "scenario: init\nitems:\n  - id: UX1\n    name: 用户追加\n    auto: true\n"
        "    severity: WARN\n    check:\n      type: command\n      cmd: 'true'\n      expect_rc: 0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXUS_HOME", str(home))
    from nexusos_gate import gate_engine
    gate_engine._USER_CHECKS_D_CACHE.clear()
    cfg = gate_engine._load_scenario("init")
    ids = [it.get("id") for it in cfg.get("items", [])]
    assert "UX1" in ids and ids.count("UX1") == 1
    # 内置项未被动
    assert any(i for i in ids if i != "UX1")
    gate_engine._USER_CHECKS_D_CACHE.clear()


def test_real_entry_points_registered():
    """本包 pyproject 五 check 真实注册在案（安装态断言；未安装态 skip 留给冒烟阶段）。"""
    from nexusos_gate import gate_engine
    eps = importlib.metadata.entry_points(group="nexusos.gate.checks")
    names = {e.name for e in eps}
    if not names:
        pytest.skip("当前环境未安装含 entry_points 的 nexusos-gate dist（干净 venv 冒烟阶段验证）")
    assert {"config_key_refs", "codegraph_wrapper", "complexity_aware",
            "doc_consistency", "e2e_suite_evidence", "persist_pool_ledger"} <= names
    # 引擎 CHECK_PLUGINS 含协议注入（合并后可调）
    assert "e2e_suite_evidence" in gate_engine.CHECK_PLUGINS
