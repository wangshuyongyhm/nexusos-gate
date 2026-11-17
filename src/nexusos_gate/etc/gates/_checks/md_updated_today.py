"""检查类型: md_updated_today — 今日改动 .md 的 updated 字段同步（persist P15，Task980，2026-09-01）。

管什么：落盘清单瘦身配套（09010832 拍板 17+P11→11 项），原人工 #11「改过的核心文件
updated 字段为今天」转 gate 自动。扫 touched_dirs 下今日 mtime 的 .md，frontmatter
含 updated: 且值 ≠ 今日 → WARN「今日改动但 updated 未更」。

为什么只警今日 mtime 的文件：存量旧日期文件海量，全库扫 + REJECT 会拦死所有落盘
（任务书已排除方案）。为什么 WARN 不 REJECT：迁移期旧 updated 属常态，报出即提醒
（P11-P14 先例同口径）。

跳过不警（宁漏报不误报）：无 frontmatter / 无 updated 字段（业务文件不强制）/
updated 值解析不出日期段 / touched_dirs 或 date 缺失（无法判定「今日」）。
防呆：条目路径不存在 → 跳过该条（目录可能已外迁归档），不静默整体 pass。
"""
import os
import re
from datetime import datetime
from pathlib import Path

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UPDATED_RE = re.compile(r"^updated:\s*['\"]?(\d{4}-\d{2}-\d{2})", re.MULTILINE)
_SCAN_CAP = 3000  # 单次检查文件数上限，防极端 touched_dirs 失控


def _coerce_list(value):
    """把 value 规整成 list[str]（gate 占位符可能传 "[]" repr 串，对齐 pool_rows_flipped）。"""
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
    return []


def _frontmatter_updated(path: Path):
    """读文件头 frontmatter 的 updated 日期段。无 frontmatter/无字段/解析不出 → None。"""
    try:
        head = path.open("r", encoding="utf-8", errors="ignore").read(8192)
    except OSError:
        return None
    if not head.startswith("---"):
        return None
    end = head.find("\n---", 3)
    block = head[:end] if end != -1 else head
    m = _UPDATED_RE.search(block)
    return m.group(1) if m else None


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params:
      dirs: touched_dirs 列表（缺省回落 context.touched_dirs）
      date: 今日 YYYY-MM-DD（缺省回落 context.date）
      vault_root: Vault 根（占位符未解析/缺失时回落 cwd）
    返回: (passed, detail)  # severity WARN
    """
    dirs = _coerce_list(params.get("dirs", [])) or _coerce_list(context.get("touched_dirs", []))
    today = str(params.get("date") or context.get("date") or "")
    if not dirs:
        return True, "无 touched_dirs，跳过 updated 检查"
    if not _DATE_RE.match(today):
        return True, f"date 缺失/非法({today or '空'})，无法判定今日，跳过"

    vault_root = params.get("vault_root") or context.get("vault_root") or ""
    if not vault_root or "{" in vault_root:
        vault_root = os.getcwd()
    vault = Path(vault_root)

    # 收集 touched 条目下今日 mtime 的 .md（条目可为目录或单个 .md 文件）
    today_files, missing = [], []
    for d in dirs:
        p = vault / d
        if p.is_file() and p.suffix == ".md":
            candidates = [p]
        elif p.is_dir():
            candidates = list(p.rglob("*.md"))
        else:
            missing.append(str(d))
            continue
        for f in candidates:
            try:
                if datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d") == today:
                    today_files.append(f)
            except OSError:
                continue
            if len(today_files) >= _SCAN_CAP:
                break

    issues, has_updated = [], 0
    for f in today_files[:_SCAN_CAP]:
        upd = _frontmatter_updated(f)
        if upd is None:
            continue  # 无 frontmatter/无 updated/解析不出——业务文件不强制
        has_updated += 1
        if upd != today:
            rel = f.relative_to(vault) if str(f).startswith(str(vault)) else f
            issues.append(f"{rel}（updated: {upd}）")

    cap_note = f"，超上限截断至 {_SCAN_CAP}" if len(today_files) >= _SCAN_CAP else ""
    miss_note = f"；{len(missing)} 条路径不存在已跳过" if missing else ""
    if issues:
        return False, ("⚠️ 今日改动但 updated 未更: " + "; ".join(issues[:5])
                       + (f" 等 {len(issues)} 处" if len(issues) > 5 else ""))
    return True, (f"✅ 今日 mtime .md {len(today_files)} 个：{has_updated} 个带 updated 均为今日"
                  f"{cap_note}{miss_note}")
