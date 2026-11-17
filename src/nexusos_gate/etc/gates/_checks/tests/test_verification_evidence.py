"""test_verification_evidence.py — C8 检查的单元测试。

08040834 随 C8 处女原则重写一起创建。
覆盖：3 路径（文档豁免/verify 文件/测试覆盖）+ REJECT + 旧标记失效。

运行：python3 -m pytest nexusos_xdr/etc/gates/_checks/test_verification_evidence.py -v
或：  python3 nexusos_xdr/etc/gates/_checks/test_verification_evidence.py（直接跑）
"""
import os
import sys
import tempfile

# 让 import 能找到 verification_evidence（同目录）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verification_evidence import check, _has_no_code, _has_verify_file, _has_test_coverage

PROJECT_ROOT = os.environ.get("NEXUS_VAULT_ROOT") or ""


def _ctx(files, msg="", root=PROJECT_ROOT):
    """构造 check() 的 context。"""
    return {"changed_files": files, "commit_msg": msg, "project_root": root}


def test_doc_only_exempt():
    """路径1: 纯文档/配置豁免。"""
    passed, _ = check({}, _ctx(["README.md", "config.yaml"]), "test")
    assert passed, "纯文档应豁免"
    passed, _ = check({}, _ctx(["notes.md"]), "test")
    assert passed, "单个 .md 应豁免"


def test_doc_only_rejects_mixed():
    """路径1: 文档+代码混合不豁免。"""
    assert not _has_no_code(["README.md", "script.py"]), "混合不应豁免"
    assert not _has_no_code(["script.sh"]), "纯代码不应豁免"


def test_non_code_exempt():
    """Task508: 非代码文件豁免（无扩展名/数据/文档/二进制）。"""
    assert _has_no_code([".gitignore"]), ".gitignore 无扩展名应豁免"
    assert _has_no_code(["Makefile"]), "Makefile 无扩展名应豁免"
    assert _has_no_code(["schema.sql"]), ".sql 应豁免（非代码）"
    assert _has_no_code(["report.docx"]), ".docx 应豁免"
    assert _has_no_code(["data.dump"]), ".dump 应豁免"
    assert _has_no_code(["config.yaml", "notes.md"]), ".yaml+.md 应豁免"
    assert _has_no_code(["vault-health.json"]), ".json 应豁免"
    assert _has_no_code(["icon.svg"]), ".svg 应豁免"
    # 混合：非代码 + 代码 → 不豁免
    assert not _has_no_code([".gitignore", "script.py"]), "含代码不应豁免"


def test_verify_file_passes():
    """路径2: commit 含 verify_*.md / test_*.py 通过。"""
    passed, _ = check({}, _ctx(["code.py", "verify_code.md"]), "test")
    assert passed, "verify_*.md 应通过"
    passed, _ = check({}, _ctx(["code.py", "test_code.py"]), "test")
    assert passed, "test_*.py 应通过"
    passed, _ = check({}, _ctx(["code.sh", "test_code.sh"]), "test")
    assert passed, "test_*.sh 应通过（bash 脚本测试）"


def test_msg_marker_no_longer_passes():
    """🔴 关键回归：旧的 commit_msg 标记路径已移除。

    08040834 处女原则重写前：[verified:场景验证] 标记可让代码改动通过。
    重写后：标记不再算验证证据，必须 REJECT。
    """
    # 代码改动 + commit_msg 含旧标记 → 应该 REJECT（标记失效）
    passed, detail = check({}, _ctx(["code.py"], msg="[verified:场景验证] 修复"), "test")
    assert not passed, f"旧标记应失效（REJECT），但 passed={passed}"
    assert "无验证证据" in detail, f"detail 应说明无证据，实际: {detail}"

    # 其他旧标记格式也全部失效
    for marker in ["[tested:unit]", "[checked:manual]", "verified: yes", "tested: ok"]:
        passed, _ = check({}, _ctx(["code.py"], msg=marker), "test")
        assert not passed, f"旧标记 '{marker}' 应失效"


def test_test_coverage_py():
    """路径3: .py 有对应 test_*.py 通过。"""
    # 用临时目录构造 code.py + test_code.py
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "code.py"), "w").close()
        open(os.path.join(tmp, "test_code.py"), "w").close()
        assert _has_test_coverage(["code.py"], tmp), "test_code.py 同目录应覆盖"
        assert _has_test_coverage(["code.py"], tmp), "重复调用应稳定"


def test_test_coverage_sh():
    """路径3: .sh 有对应 test_*.sh 通过（08040834 新增 bash 支持）。"""
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "script.sh"), "w").close()
        open(os.path.join(tmp, "test_script.sh"), "w").close()
        assert _has_test_coverage(["script.sh"], tmp), "test_script.sh 应覆盖 .sh"


def test_no_coverage_rejects():
    """路径3 不满足: 无对应 test → REJECT。"""
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "lonely.py"), "w").close()
        assert not _has_test_coverage(["lonely.py"], tmp), "无 test 应不覆盖"


def test_empty_files_passes():
    """无 changed_files → pass（空 commit）。"""
    passed, _ = check({}, _ctx([]), "test")
    assert passed, "空 changed_files 应 pass"


def test_reject_message_helpful():
    """REJECT 时 detail 应含修复指引（告诉开发者怎么补证据）。"""
    passed, detail = check({}, _ctx(["code.py"]), "test")
    assert not passed
    assert "test_*.py" in detail or "test_*.sh" in detail, "应提示 test 文件"
    assert "verify_*.md" in detail, "应提示 verify 文件"


def test_real_world_deletion_mentioned():
    """真实场景：deletion_mentioned.py 改了，无对应 test → REJECT（需补 verify 或 test）。"""
    files = ["nexusos_xdr/etc/gates/_checks/deletion_mentioned.py"]
    passed, detail = check({}, _ctx(files), "test")
    # deletion_mentioned.py 确实无 test_deletion_mentioned.py
    assert not passed, f"deletion_mentioned.py 无 test 应 REJECT，但 passed={passed}"


def test_task_verify_requires_substantive_content():
    """🔴 Task1552 N1 回归：空壳 task 文件不再洗白（1545 发现）。

    旧判据只看路径形态（task/ 前缀+验证后缀）——引用任意既有任务的
    空壳 reproduce.sh 即可豁免全部生产代码的验证证据。
    收紧后须文件存在且有实质内容（非空/非仅 shebang/非纯空白）。
    """
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "prod.py"), "w").write("x = 1\n")
        # 空壳1：仅 shebang
        fake_dir = os.path.join(tmp, "task", "999-fake")
        os.makedirs(fake_dir)
        open(os.path.join(fake_dir, "reproduce.sh"), "w").write("#!/bin/bash\n")
        files = ["prod.py", "task/999-fake/reproduce.sh"]
        passed, _ = check({}, _ctx(files, root=tmp), "test")
        assert not passed, "仅 shebang 的空壳 reproduce.sh 不应洗白"

        # 空壳2：幽灵路径（文件不存在）
        files = ["prod.py", "task/888-ghost/reproduce.sh"]
        passed, _ = check({}, _ctx(files, root=tmp), "test")
        assert not passed, "不存在的幽灵 task 文件不应洗白"

        # 正路：有实质内容的 reproduce.sh 仍通过
        open(os.path.join(fake_dir, "reproduce.sh"), "w").write(
            "#!/bin/bash\npython3 prod.py --verify\n")
        files = ["prod.py", "task/999-fake/reproduce.sh"]
        passed, _ = check({}, _ctx(files, root=tmp), "test")
        assert passed, "有实质内容的 reproduce.sh 应通过"


if __name__ == "__main__":
    # 直接运行模式（无 pytest 也能跑）
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
