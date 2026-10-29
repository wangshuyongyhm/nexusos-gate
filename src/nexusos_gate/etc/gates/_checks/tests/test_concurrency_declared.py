#!/usr/bin/env python3
"""test_concurrency_declared.py — C17 插件三路判据单测（Task1542）。

跑法：python3 test_concurrency_declared.py   （或 pytest）
断言：非代码豁免 / [concurrency:] 标记 / test_*concurrency* 陪跑 / 无声明 WARN / read-only 显式豁免
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from concurrency_declared import check  # noqa: E402

CODE = "05-System/自动化脚本/pypi/nexusos-mem/src/nexusos_mem/shared.py"
CODE2 = "05-System/自动化脚本/e2e-suite/chains/chain-f.sh"
DOC = "06-Memory/未决问题池.md"

CASES = [
    ("空改动跳过", [], "", True),
    ("纯文档豁免", [DOC], "docs: 更新池", True),
    ("msg 声明（多写者）",
     [CODE], "fix: x [concurrency:多写者-同目标并发调用加 flock]", True),
    ("msg 声明（read-only 显式豁免）", [CODE2], "chore: 只改注释 [concurrency:read-only]", True),
    ("并发测试陪跑", [CODE, "task/1542-x/output/files/test_concurrency_apply.sh"], "fix: x", True),
    ("无声明→WARN",
     [CODE], "fix: 随便改一行", False),
    ("无声明（多文件）→WARN", [CODE, CODE2], "refactor: 清理", False),
]


def main():
    failed = []
    for name, files, msg, expect_pass in CASES:
        passed, detail = check({}, {"changed_files": files, "commit_msg": msg}, "agent-a")
        ok = (passed == expect_pass)
        mark = "✔" if ok else "✘"
        print(f"  {mark} {name:26} passed={passed} (期望 {expect_pass}) | {detail[:70]}")
        if not ok:
            failed.append(name)
    print()
    print(f"汇总：{len(CASES) - len(failed)}/{len(CASES)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
