"""test_git_diff_parsers.py — git diff 解析层回归（Task1552 S1/S2 收口的守护测试）。

背景（1545 审查实证）：quotePath 缺失 + lstrip("b/") 字符集误剥曾致
C1 中文路径全量误拦、C6 报错 b/ 前缀残留、C14/C15 中文 .py 漏检。
1552 收口到 _gitcmd（run_git 恒带 quotePath=false + diff_b_path 精确剥除），
本测试构造中文路径 git repo 锁行为。

运行：python3 -m pytest nexusos_gate/etc/gates/_checks/test_git_diff_parsers.py -v
或：  python3 test_git_diff_parsers.py（直接跑，无 pytest 也能跑）
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _gitcmd
import comment_out_detection as C6
import deletion_mentioned as C4
import git_diff_scope as C1
import grep_in_diff as C2


def _make_repo(tmp: str):
    """构造含中文路径/中文文件名/b 开头文件的 git repo，返回 staged 状态。"""
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp, capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    open(os.path.join(tmp, "seed.txt"), "w").write("init\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    zh_dir = os.path.join(tmp, "06-Memory", "MEM图谱")
    os.makedirs(zh_dir, exist_ok=True)
    open(os.path.join(zh_dir, "卡A.md"), "w", encoding="utf-8").write("# print(hello)\n卡片\n")
    open(os.path.join(tmp, "b-fix.py"), "w").write("x = 1\n# result = run(x)\n")
    git("add", "-A")


def test_run_git_quotepath_off():
    """run_git 输出的中文路径是 UTF-8 原文（无引号/无八进制）。"""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        rc, out, _ = _gitcmd.run_git(["diff", "--cached", "--name-only"], cwd=tmp)
        assert rc == 0
        assert '"06-' not in out and "\\345" not in out, f"仍有引号/八进制: {out!r}"
        assert "06-Memory/MEM图谱/卡A.md" in out


def test_diff_b_path_forms():
    """S1 核心回归：三种 +++ 头形态解析正确。"""
    assert _gitcmd.diff_b_path('"b/06-Memory/MEM图谱/卡A.md"') == "06-Memory/MEM图谱/卡A.md"
    assert _gitcmd.diff_b_path("b/b-fix.py") == "b-fix.py", "b 开头文件名不能被啃"
    assert _gitcmd.diff_b_path("b/normal.py") == "normal.py"
    assert _gitcmd.diff_b_path("/dev/null") == "/dev/null"


def test_c1_chinese_scope_no_false_reject():
    """S2a 核心回归：中文 task_scope 内的中文路径文件不再误拦。"""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        passed, detail = C1.check(
            {"task_scope": ["06-Memory/MEM图谱"], "project_root": tmp},
            {"project_root": tmp}, "test")
        # b-fix.py 越界是真实违规，但中文卡A不得出现在 out_of_scope
        assert "卡A" not in detail, f"中文路径仍被误判: {detail}"
        assert "06-Memory/MEM图谱" in detail or passed, "out_of_scope 列表应含可读中文路径"


def test_c6_no_b_prefix_residue():
    """S1 端到端：C6 报错路径无 b/ 前缀残留、b-fix.py 不被啃、中文可读。"""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        passed, detail = C6.check({"project_root": tmp}, {"project_root": tmp}, "test")
        assert not passed, "构造的注释化代码应被发现"
        assert "b/" not in detail, f"b/ 前缀残留: {detail}"
        assert "\\3" not in detail, f"八进制转义残留: {detail}"
        assert "卡A.md" in detail, f"中文路径应可读: {detail}"
        assert "-fix.py" in detail and "b-fix.py" in detail, f"b 开头文件名被啃: {detail}"


def test_c2_chinese_md_exclude_still_works():
    """收口后 C2 排除规则对中文路径 .md 仍生效（1545 自纠错三的锁定）。"""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        # 卡A.md 里是注释不是 sleep；b-fix.py 无 sleep → 应零命中 pass
        passed, detail = C2.check(
            {"pattern": r"time\.sleep",
             "exclude_files": ["*test*", "*.md", "task/*"],
             "project_root": tmp},
            {"project_root": tmp}, "test")
        assert passed, f"不应误报: {detail}"
        assert "扫描" in detail  # 正常完成扫描而非跳过


def test_c4_numstat_chinese_readable():
    """C4 numstat 中文路径不再八进制（真实删除行场景）。"""
    with tempfile.TemporaryDirectory() as tmp:
        _make_repo(tmp)
        # staged 状态先落 commit，再覆写产生真实删除行
        subprocess.run(["git", "commit", "-qm", "add files"], cwd=tmp, capture_output=True)
        open(os.path.join(tmp, "06-Memory", "MEM图谱", "卡A.md"), "w",
             encoding="utf-8").write("新内容\n")  # 覆写：-2/+1
        subprocess.run(["git", "add", "-A"], cwd=tmp, capture_output=True)
        # 无关键词 → REJECT 且无八进制
        passed, detail = C4.check(
            {"commit_msg": "fix: update", "project_root": tmp},
            {"commit_msg": "fix: update", "project_root": tmp}, "test")
        assert not passed, f"英文 update 未提及删除应 REJECT: {detail}"
        assert "\\345" not in detail, f"八进制残留: {detail}"
        # 有关键词 → pass 分支的文件样本是可读中文（S2 numstat 验证点）
        passed, detail = C4.check(
            {"commit_msg": "chore: 清理旧内容", "project_root": tmp},
            {"commit_msg": "chore: 清理旧内容", "project_root": tmp}, "test")
        assert passed, f"清理属 MENTION 关键词应 pass: {detail}"
        assert "卡A.md" in detail, f"样本应含可读中文路径: {detail}"
        assert "\\345" not in detail, f"八进制残留: {detail}"


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed_count = 0
    failed = []
    for t in tests:
        try:
            t()
            print(f"  ✅ {t.__name__}")
            passed_count += 1
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
            failed.append(t.__name__)
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}")
            failed.append(t.__name__)
    print(f"\n总计: {passed_count}/{len(tests)} 通过")
    if failed:
        print(f"失败: {failed}")
        sys.exit(1)
    print("✅ 全部通过")
