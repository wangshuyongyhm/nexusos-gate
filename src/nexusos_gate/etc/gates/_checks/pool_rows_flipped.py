"""检查类型: pool_rows_flipped — 池行闭环一致性（persist P14，池#48 立项，2026-08-31）。

管什么：落盘时扫描本会话动过的 task 目录，任务书 parent_anchors 引用了未决池行、
report 机读块已宣告 complete、但池里那一行还没翻「闭环」→ WARN 提醒翻行。
治「池漂移」：08311900 会话实证 6 行滞留 11-12 天险些派重复单——原来翻行只靠
persist 清单 #17 自觉，本检查把人训变成机器拦。

为什么 WARN 不 REJECT（刻意设计，与 P11/P12/P13 先例一致）：任务 done 但池行留
观察口径（如 #46 半闭环）、多会话接力翻行，都是合法场景，REJECT 会误伤。报出即提醒。

跳过（翻行未到期，不报）：task 无池引用 / report 无机读块 / status 非 complete
（complete|blocked|continue 是 task-spec §2 第6项枚举，blocked/continue=还没到翻行时点）。
防呆：池文件缺失/不可读 → check 直接 False（不静默 pass，让落盘者看见检查自身坏了）。

池编号冲突（21-27 双系列，池头有注）：同号多行时任一行含「闭环」即算已翻——宁漏报不误报。
"""
import os
import re
from pathlib import Path

# 池引用三形态（任务书 §7 陷阱4）：
#   [[06-Memory/未决问题池]] #32  /  [[未决问题池]] #589  /  备注「池#48」
_POOL_REF_PATTERNS = [
    re.compile(r"未决问题池[^\n]{0,80}?#(\d+)"),
    re.compile(r"池#(\d+)"),
]

# task 目录提取：touched_dirs 条目形如 "task/967-mirror-i4"（可能带尾部 / 或嵌套）
_TASK_DIR_RE = re.compile(r"(task/[^\s|,\]\"]+?)(?:/|$)")

# report 机读块（task-spec §2 第6项：尾部 fenced yaml，status 枚举 complete|blocked|continue）
_STATUS_RE = re.compile(r"^\s*status:\s*([A-Za-z]+)", re.MULTILINE)
_YAML_FENCE_RE = re.compile(r"```yaml(.*?)```", re.DOTALL)


def _coerce_list(value):
    """把 value 规整成 list[str]（gate 占位符可能传 "[]" 字符串，对齐 agent_archive_updated）。"""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(d) for d in value if d]
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            try:
                import ast
                parsed = ast.literal_eval(s)
                return [str(d) for d in parsed if d] if isinstance(parsed, list) else []
            except Exception:
                return []
        return [s] if s else []
    return [str(value)] if value else []


def _extract_pool_refs(task_md_path: Path) -> list:
    """从 task 书全文提取池行号（去重保序）。无引用返回 []。"""
    try:
        text = task_md_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    nums = []
    for pat in _POOL_REF_PATTERNS:
        for m in pat.finditer(text):
            n = m.group(1)
            if n not in nums:
                nums.append(n)
    return nums


def _report_complete(report_path: Path) -> bool:
    """report 机读块 status==complete 才算「翻行已到期」。无机读块/其他状态 → False。"""
    try:
        text = report_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    fences = _YAML_FENCE_RE.findall(text)
    if not fences:
        return False
    m = _STATUS_RE.search(fences[-1])  # 只认尾部最后一块（机读块定义在尾部）
    return bool(m and m.group(1) == "complete")


def _pool_row_closed(pool_text: str, num: str) -> bool:
    """池中 | NN | 行（同号多行任一）含「闭环」即算已翻。行不存在=未翻（WARN 报出）。"""
    row_re = re.compile(r"^\|\s*" + re.escape(num) + r"\s*\|", re.MULTILINE)
    for m in row_re.finditer(pool_text):
        if "闭环" in pool_text[m.start():pool_text.find("\n", m.start())]:
            return True
    return False


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      dirs: touched_dirs 列表（缺省回落 context.touched_dirs）
      pool_path: 池文件 vault 相对路径（缺省 06-Memory/未决问题池.md）
      vault_root: Vault 根（占位符未解析/缺失时回落 cwd）
    返回: (passed, detail)  # severity WARN
    """
    dirs = _coerce_list(params.get("dirs", [])) or _coerce_list(context.get("touched_dirs", []))
    pool_path = params.get("pool_path", "06-Memory/未决问题池.md")

    vault_root = params.get("vault_root") or context.get("vault_root") or ""
    if not vault_root or "{" in vault_root:
        vault_root = os.getcwd()
    vault = Path(vault_root)

    pool_file = vault / pool_path
    try:
        pool_text = pool_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as e:
        # 防呆：池文件读不到，检查自身失效——不静默 pass
        return False, f"⚠️ P14 自身异常: 池文件不可读 {pool_file} ({e})，池行一致性未检"

    # 收集本会话动过的 task 目录（去重）
    task_dirs = []
    for d in dirs:
        m = _TASK_DIR_RE.search(str(d))
        if m and m.group(1) not in task_dirs:
            task_dirs.append(m.group(1))
    if not task_dirs:
        return True, "无 task 目录改动，跳过池行检查"

    issues, checked = [], 0
    for td in task_dirs:
        task_md = vault / td / "input" / "task.md"
        report_md = vault / td / "output" / "report.md"
        refs = _extract_pool_refs(task_md)
        if not refs:
            continue  # 无池引用（task.md 不存在也落这里）
        if not report_md.is_file() or not _report_complete(report_md):
            continue  # 无 report / 无机读块 / status 非 complete：翻行未到期
        checked += 1
        for n in refs:
            if not _pool_row_closed(pool_text, n):
                issues.append(f"池行 #{n} 未翻闭环（{td} 已 complete）")

    if issues:
        return False, "⚠️ 池行闭环滞后: " + "; ".join(issues[:5])
    return True, f"✅ {checked} 个 complete task 的池行均已翻闭环（扫描 {len(task_dirs)} 个 task 目录）"
