#!/usr/bin/env python3
"""Task1879-A: P4 readme_synced 升级前三场景自测 + 多口径容差。

场景: 旧 README→fail(升 REJECT 后被拦) / 新 README→pass / 无 README→pass 不误报
附加: file_count 多口径（md/全文件/剔缓存）容差 + persist.yaml P4=REJECT 配置断言。
风格参考 nexusos_xdr/test_task592_link_integrity.py（importlib 直载插件）。
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import importlib.util as _ilu


def _load_mod(name):
    if name in sys.modules:
        return sys.modules[name]
    _f = SCRIPT_DIR / f"{name}.py"
    _spec = _ilu.spec_from_file_location(name, _f)
    _m = _ilu.module_from_spec(_spec)
    sys.modules[name] = _m
    _spec.loader.exec_module(_m)
    return _m


_vaultlink = _load_mod("_vaultlink")
readme_synced_check = _load_mod("readme_synced").check

TODAY = datetime.now().strftime("%Y-%m-%d")


def _mk_readme(d: Path, updated: str, file_count=None):
    fm = ["---", "title: t", f"updated: {updated}"]
    if file_count is not None:
        fm.append(f"file_count: {file_count}")
    fm.append("---")
    (d / "README.md").write_text("\n".join(fm) + "\n# x\n", encoding="utf-8")


def test_stale_readme_fails(tmp_path):
    """场景1: 旧 README（updated 过期）→ fail（升级 REJECT 后被拦）。"""
    d = tmp_path / "proj"
    d.mkdir()
    _mk_readme(d, updated="2020-01-01")
    p, detail = readme_synced_check(
        {"dirs": [str(d)], "date": TODAY}, {"touched_dirs": [str(d)], "date": TODAY}, "agent-a")
    assert p is False and "updated" in detail


def test_synced_readme_passes(tmp_path):
    """场景2: 新 README（updated=today，file_count 命中 md 口径）→ pass。"""
    d = tmp_path / "proj"
    d.mkdir()
    (d / "a.md").write_text("x", encoding="utf-8")
    (d / "b.md").write_text("x", encoding="utf-8")
    _mk_readme(d, updated=TODAY, file_count=3)  # README 自身也算 → 3 md
    p, detail = readme_synced_check(
        {"dirs": [str(d)], "date": TODAY}, {"touched_dirs": [str(d)], "date": TODAY}, "agent-a")
    assert p is True, detail


def test_no_readme_passes(tmp_path):
    """场景3: 目录无 README → pass 不误报（Task1879-A①）。"""
    d = tmp_path / "proj"
    d.mkdir()
    (d / "a.md").write_text("x", encoding="utf-8")
    p, detail = readme_synced_check(
        {"dirs": [str(d)], "date": TODAY}, {"touched_dirs": [str(d)], "date": TODAY}, "agent-a")
    assert p is True, detail


def test_file_count_multicaliber(tmp_path):
    """A③: 全文件口径与 md 口径并存——两种声明都过，离谱声明拦。"""
    d = tmp_path / "proj"
    d.mkdir()
    for i in range(9):
        (d / f"m{i}.md").write_text("x", encoding="utf-8")
    for i in range(90):
        (d / f"f{i}.txt").write_text("x", encoding="utf-8")
    # 全文件口径: 100 个文件（9 md + 90 txt + README）
    _mk_readme(d, updated=TODAY, file_count=100)
    p, detail = readme_synced_check({"dirs": [str(d)], "date": TODAY}, {}, "agent-a")
    assert p is True, f"全文件口径应过: {detail}"
    # md 口径: 10 md（9 + README）
    _mk_readme(d, updated=TODAY, file_count=10)
    p, detail = readme_synced_check({"dirs": [str(d)], "date": TODAY}, {}, "agent-a")
    assert p is True, f"md 口径应过: {detail}"
    # 离谱声明 → 拦
    _mk_readme(d, updated=TODAY, file_count=500)
    p, detail = readme_synced_check({"dirs": [str(d)], "date": TODAY}, {}, "agent-a")
    assert p is False and "file_count" in detail


def test_file_count_nocache_caliber(tmp_path):
    """A③: 剔缓存口径——__pycache__ 内文件不计入第三口径。"""
    d = tmp_path / "proj"
    (d / "__pycache__").mkdir(parents=True)
    for i in range(50):
        (d / "__pycache__" / f"x{i}.pyc").write_text("x", encoding="utf-8")
    (d / "a.py").write_text("x", encoding="utf-8")
    # 剔缓存全文件口径: a.py + README = 2
    _mk_readme(d, updated=TODAY, file_count=2)
    p, detail = readme_synced_check({"dirs": [str(d)], "date": TODAY}, {}, "agent-a")
    assert p is True, f"剔缓存口径应过: {detail}"


def test_persist_yaml_p4_is_reject():
    """配置断言: persist.yaml P4 severity 已升 REJECT。"""
    cfg = yaml.safe_load((SCRIPT_DIR.parent / "persist.yaml").read_text(encoding="utf-8"))
    p4 = [i for i in cfg["items"] if i.get("id") == "P4"]
    assert p4 and p4[0]["severity"] == "REJECT", f"P4 severity={p4}"
