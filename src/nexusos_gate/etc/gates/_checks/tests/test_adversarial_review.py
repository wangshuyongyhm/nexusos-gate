"""test_adversarial_review.py — C13 对抗式审查 check 的单元测试。

覆盖 4 证据路径 + REJECT + 非代码豁免。

运行：python3 nexusos_xdr/etc/gates/_checks/test_adversarial_review.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from adversarial_review import check

PROJECT_ROOT = os.environ.get("NEXUS_VAULT_ROOT") or ""


def _ctx(files, msg="", root=PROJECT_ROOT):
    return {"changed_files": files, "commit_msg": msg, "project_root": root}


def test_non_code_exempt():
    """非代码文件豁免。"""
    passed, _ = check({}, _ctx(["README.md"]), "test")
    assert passed, ".md 应豁免"
    passed, _ = check({}, _ctx([".gitignore"]), "test")
    assert passed, ".gitignore 应豁免"
    passed, _ = check({}, _ctx(["config.yaml", "notes.md"]), "test")
    assert passed, ".yaml+.md 应豁免"


def test_code_no_evidence_warns():
    """代码改动无证据 → False（WARN）。"""
    passed, detail = check({}, _ctx(["script.py"], msg="fix bug"), "test")
    assert not passed, "代码无证据应 WARN"
    assert "对抗式审查" in detail or "adversarial" in detail.lower()


def test_code_with_msg_marker_passes():
    """代码 + commit_msg [adversarial:...] → True。"""
    passed, _ = check({}, _ctx(["script.py"], msg="fix [adversarial:边界空值]"), "test")
    assert passed, "commit_msg 标记应通过"


def test_code_with_test_passes():
    """代码 + test_*.py 陪跑 → True。"""
    passed, _ = check({}, _ctx(["script.py", "test_script.py"]), "test")
    assert passed, "test 陪跑应通过"
    passed, _ = check({}, _ctx(["foo.py", "foo_test.py"]), "test")
    assert passed, "_test.py 后缀也应通过"


def test_code_with_verify_keyword_passes():
    """代码 + verify_*.md 含对抗式关键词 → True。"""
    with tempfile.TemporaryDirectory() as tmp:
        verify_path = os.path.join(tmp, "verify_feature.md")
        with open(verify_path, "w") as f:
            f.write("# 对抗式审查\n测试了边界值和反例")
        ctx = {"changed_files": ["script.py", "verify_feature.md"],
               "commit_msg": "fix", "project_root": tmp}
        passed, detail = check({}, ctx, "test")
        assert passed, f"verify 文件含对抗式关键词应通过, detail={detail}"


def test_code_with_verify_no_keyword_fails():
    """代码 + verify_*.md 不含关键词 → False。"""
    with tempfile.TemporaryDirectory() as tmp:
        verify_path = os.path.join(tmp, "verify_feature.md")
        with open(verify_path, "w") as f:
            f.write("# 普通验证\n跑了 happy path")
        ctx = {"changed_files": ["script.py", "verify_feature.md"],
               "commit_msg": "fix", "project_root": tmp}
        passed, _ = check({}, ctx, "test")
        assert not passed, "verify 文件不含关键词应 WARN"


def test_empty_files_passes():
    """无 changed_files → pass。"""
    passed, _ = check({}, _ctx([]), "test")
    assert passed, "空 changed_files 应 pass"


def test_mixed_code_non_code_warns():
    """混合（.py + .md）→ 有代码 → 需证据。"""
    passed, _ = check({}, _ctx(["README.md", "script.py"], msg="update"), "test")
    assert not passed, "含代码不应豁免"


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
