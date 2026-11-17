"""检查类型: concurrency_declared — 并发考虑声明（C17，Task1542，WARN）。

来源：池 #212 用户定向「写出的代码一定要有并发考虑」+ Task1529 压测基线
（同目标并发派单/回调洪流/op-log 窗口/PG 行锁/文件同写 → 3 降级 0 破坏）。

设计边界（任务书 §3）：
  - **只做声明式自查触发器，不做静态并发分析**（并发正确性机器验不了——目标是"想过没有"）。
  - WARN 起步（C13/C14-C16 同款路径）：跑稳 + 误报率人工评估 <20% 后由主控裁决升 REJECT。
  - 与 C13（对抗式审查）证据标记**各自独立**：`[adversarial:...]` ≠ `[concurrency:...]`。

三条证据路径（任一满足即 pass）：
  1. 非代码豁免: changed_files 不含代码扩展名（复用 verification_evidence._has_no_code）
  2. commit_msg 标记: 含 `[concurrency:...]`（声明考虑了哪项 + 什么防护）
  3. test 陪跑: changed_files 含并发相关测试文件名（test_*concurrency* / *concurrency*test*）
"""
import os
import re

try:
    from verification_evidence import _has_no_code, _coerce_files
except ImportError:
    from .verification_evidence import _has_no_code, _coerce_files

_CONCURRENCY_MSG = re.compile(r'\[concurrency:\s*(.*?)\]', re.IGNORECASE | re.DOTALL)


def _is_concurrency_test(path: str) -> bool:
    """并发相关测试文件：test_*concurrency* / *concurrency*_test* / *concurrency*.sh"""
    base = os.path.basename(path).lower()
    if "concurrency" not in base:
        return False
    return (base.startswith("test_") or "_test" in base or base.endswith(".sh")
            or base.endswith(".py") and "test" in base)


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: (无, 全从 context 取)
    context:
      changed_files: 改动文件列表
      commit_msg: 提交信息
    返回: (passed, detail)  — severity 由 code.yaml 控制（WARN）
    """
    changed = _coerce_files(context.get("changed_files"), context)
    if not changed:
        return True, "无改动,跳过"

    # 路径1: 非代码豁免（纯文档/配置/纯只读产物）
    if _has_no_code(changed):
        return True, "非代码改动,豁免（无须并发声明）"

    # 路径2: commit_msg 标记
    msg = context.get("commit_msg", "") or ""
    m = _CONCURRENCY_MSG.search(msg)
    if m:
        declared = " ".join(m.group(1).split())[:80]
        return True, f"commit_msg 含并发考虑声明: {declared or '(空声明)'}"

    # 路径3: 并发测试陪跑
    for f in changed:
        if _is_concurrency_test(str(f)):
            return True, f"有并发测试陪跑: {os.path.basename(str(f))}"

    # 全不满足 → WARN 提醒（不拦 commit）
    code_files = [os.path.basename(str(f)) for f in changed
                  if os.path.splitext(str(f))[1].lower() in (".py", ".sh", ".js", ".ts", ".mjs", ".cjs")
                  or str(f).endswith((".py", ".sh"))]
    sample = ", ".join(code_files[:3]) or "见 changed_files"
    return False, (
        f"代码改动（{sample}）未见并发考虑声明。请自查四项："
        "① 多写者（同目标并发调用）② 竞态窗口（check-then-set / 锁粒度）"
        "③ 锁边界（flock/行锁/文件锁的持有范围）④ 幂等（重试/重复回调/重复提交）。"
        "声明方式任选：commit_msg 加 `[concurrency:考虑了什么+防护]`"
        "（纯只读/无并发面用 `[concurrency:read-only]`），或补 test_*concurrency* 陪跑。"
        "依据：池 #212 + Task1529 压测基线（10安全/3降级/0破坏）"
    )
