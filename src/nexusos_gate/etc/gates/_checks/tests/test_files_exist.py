"""test_files_exist.py — G1 files_exist 检查的单测（Task898 修复）。

覆盖：三级路径解析语义——Vault 内存在/缺失、Vault 外绝对路径、report 机读块
repo_root 外部仓库根解析、真幽灵仍拒（REJECT 语义不放松）、37571 回归
（task/ 相对路径补 Vault 根行为不得回退）、多 repo_root/相对 repo_root 拒认。

运行：python3 -m pytest nexusos_gate/etc/gates/_checks/test_files_exist.py -v
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from files_exist import check, _resolve_path, _repo_roots_from_context

VAULT_ROOT = os.environ.get("NEXUS_VAULT_ROOT") or ""


def _bot_repo():
    """量化仓测试路径：env 覆盖（CI/他机零耦合），无 env 时返回空串→测试 skip。"""
    return os.environ.get("NEXUS_TEST_BOT_REPO") or ""


def _mk_repo_with_file(tmpdir, rel="bot/adapters/mock_broker.py"):
    """构造 Vault 外仓库形态（真实文件）+ 返回 (repo_root, rel)。"""
    p = os.path.join(tmpdir, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("# test fixture\n")
    return tmpdir, rel


def _mk_report_with_repo_root(tmpdir, repo_root):
    """构造含 repo_root 机读块的 report.md。"""
    rp = os.path.join(tmpdir, "output", "report.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    open(rp, "w").write(
        "# t\n\n```yaml\nstatus: complete\nrepo_root: %s\n```\n" % repo_root)
    return rp


# ================================================== ① Vault 内存在
def test_vault_file_exists_pass():
    """① Vault 内真实文件（task/ 相对路径补 Vault 根, 37571 行为保持）。"""
    real = os.path.join(VAULT_ROOT, "05-System", "NEXUS-CONSTRAINT", "index.md")
    rel = "05-System/NEXUS-CONSTRAINT/index.md"
    assert os.path.isfile(real), "fixture 前置: Vault 内文件真实存在"
    passed, detail = check({"jsonpath": "files"}, {"files": [rel]}, "t")
    assert passed, detail
    assert "external-repo" not in detail


# ================================================== ② 真幽灵仍拒
def test_ghost_missing_reject():
    """② Vault 内缺失且无 repo_root → REJECT（拦截语义不放松, 陷阱1）。"""
    passed, detail = check(
        {"jsonpath": "files"},
        {"files": ["task/000-not-exist/output/ghost.md"]}, "t")
    assert not passed, "真幽灵必须 REJECT"
    assert "不存在" in detail


# ================================================== ③ Vault 外绝对路径
def test_external_absolute_path_pass():
    """③ 绝对路径直接存在性判定（文件系统真相, 888 files_real 形态）。"""
    bot_repo = _bot_repo()
    if not bot_repo:
        print("skip: NEXUS_TEST_BOT_REPO 未设置")
        return
    real = os.path.join(bot_repo, "bot", "adapters", "mock_broker.py")
    if not os.path.isfile(real):   # 环境无量化仓时跳过（CI 容错）
        print("skip: bot repo not on this machine")
        return
    passed, detail = check({"jsonpath": "files"}, {"files": [real]}, "t")
    assert passed, detail


def test_external_absolute_ghost_reject():
    """③b 绝对路径不存在=真幽灵（外部绝对路径也拦, 不因绝对而放水）。"""
    bot_repo = _bot_repo()
    if not bot_repo:
        print("skip: NEXUS_TEST_BOT_REPO 未设置")
        return
    ghost = os.path.join(os.path.dirname(bot_repo), "05-不存在-ghost", "ghost.py")
    passed, _ = check(
        {"jsonpath": "files"},
        {"files": [ghost]},
        "t")
    assert not passed


# ================================================== ④ repo_root 外部仓库根解析
def test_repo_root_resolution_pass():
    """④ 相对路径 Vault 解析失败 → report 机读块 repo_root 二次解析 pass。"""
    with tempfile.TemporaryDirectory() as td:
        repo, rel = _mk_repo_with_file(td)
        report = _mk_report_with_repo_root(td, repo)
        ctx = {"files": [rel], "task_path_report": report}
        passed, detail = check({"jsonpath": "files"}, ctx, "t")
        assert passed, detail
        assert "external-repo" in detail, "detail 必须注明 external-repo（验收标准）"
        assert "repo_root" in detail


def test_repo_root_file_not_in_repo_reject():
    """⑤ repo_root 在场但文件不在该仓库 → 仍 REJECT（假阳性修复≠放水）。"""
    with tempfile.TemporaryDirectory() as td:
        repo, _ = _mk_repo_with_file(td)
        report = _mk_report_with_repo_root(td, repo)
        ctx = {"files": ["not/in/repo.py"], "task_path_report": report}
        passed, _ = check({"jsonpath": "files"}, ctx, "t")
        assert not passed, "repo_root 也解析不到 → 真幽灵 REJECT"


# ================================================== ⑥ 边界
def test_multiple_repo_roots_first_hit():
    """⑥ 多条 repo_root（多 fence）——任一命中即 pass。"""
    with tempfile.TemporaryDirectory() as td:
        repo_a = os.path.join(td, "repoA")
        repo_b = os.path.join(td, "repoB")
        p = os.path.join(repo_b, "x.py")
        os.makedirs(repo_b, exist_ok=True)
        open(p, "w").write("# x\n")
        rp = os.path.join(td, "report.md")
        open(rp, "w").write(
            "```yaml\nrepo_root: %s\n```\n```yaml\nrepo_root: %s\n```"
            % (repo_a, repo_b))
        ctx = {"files": ["x.py"], "task_path_report": rp}
        passed, detail = check({"jsonpath": "files"}, ctx, "t")
        assert passed, detail


def test_relative_repo_root_rejected():
    """⑦ repo_root 必须绝对路径（regex 只认 / 开头）——相对 repo_root 不认。"""
    with tempfile.TemporaryDirectory() as td:
        report = _mk_report_with_repo_root(td, "relative/path")
        roots = _repo_roots_from_context({"task_path_report": report})
        assert roots == [], "相对 repo_root 必须拒认（防相对套相对）"


def test_no_report_context_safe():
    """⑧ 无 task_path_report / report 不存在 → 外部解析路径静默不可用。"""
    assert _repo_roots_from_context({}) == []
    assert _repo_roots_from_context(
        {"task_path_report": "/not/exist/report.md"}) == []


def test_37571_regression_task_prefix():
    """⑨ 37571 回归：task/NN 相对路径仍补 Vault 根（修复不得回退）。"""
    p = _resolve_path("task/888-mock-sell-pricing-align/output/report.md")
    assert str(p).startswith(VAULT_ROOT), "task/ 相对路径必须补 Vault 根"
    assert "/05-System/" not in str(p), "不得回退补 05-System/ 前缀"


def test_repo_root_trailing_comment():
    """⑩ yaml 行尾注释形态的 repo_root 也认（888 实测踩坑固化）。"""
    with tempfile.TemporaryDirectory() as td:
        repo, rel = _mk_repo_with_file(td)
        rp = os.path.join(td, "report.md")
        open(rp, "w").write(
            "```yaml\nrepo_root: %s  # Task898 外部仓库根契约\n```\n" % repo)
        roots = _repo_roots_from_context({"task_path_report": rp})
        assert roots == [repo], f"行尾注释形态应命中: {roots}"
        ctx = {"files": [rel], "task_path_report": rp}
        passed, detail = check({"jsonpath": "files"}, ctx, "t")
        assert passed and "external-repo" in detail


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
