"""P19 pool_write_via_wrapper — 池写入走封装检查（Task1951 G2=清单 P3）.

口径（WARN 起步）：
- 池文件（06-Memory/未决问题池.md）mtime 为今日 且 ~/.pool-write.log 无今日写痕
  → WARN「本会话池写入未走 pool-safe-write.sh 封装」
- 池未动 or 有写痕 or 痕迹文件不存在（封装从未用过，首日观察）→ pass
注：任务书建议挂 P14，因 P14 已有专属语义（池行闭环一致性），独立 P19 保单一职责。
"""
from __future__ import annotations

import os
import time


def check(params: dict, context: dict, agent: str) -> tuple:
    vault_root = (context or {}).get("vault_root") or params.get("vault_root") or ""
    if not vault_root:
        return True, "P19: 无 vault_root——skip"
    pool = os.path.join(vault_root, "06-Memory", "未决问题池.md")
    if not os.path.exists(pool):
        return True, "P19: 池文件不存在——skip"
    mtime = os.path.getmtime(pool)
    if mtime < time.time() - 86400:
        return True, "P19: 池 24h 内未修改——无需封装检查"
    day_tag = time.strftime("%Y-%m-%d", time.localtime(mtime))
    log = os.path.expanduser("~/.pool-write.log")
    if not os.path.exists(log):
        return False, ("P19: 池今日被修改但从未走 pool-safe-write.sh 封装"
                       "（~/.pool-write.log 不存在）——并发写互吞风险（池#102），"
                       "统一入口：pool-safe-write.sh replace|append")
    try:
        hit = any(day_tag in ln for ln in open(log, encoding="utf-8", errors="replace"))
    except OSError:
        hit = False
    if hit:
        return True, "P19: 池写入已走 pool-safe-write.sh（写痕在案）"
    return False, ("P19: 池 %s 被修改但 ~/.pool-write.log 无当日写痕——"
                   "未走封装（并发互吞风险），下次用 pool-safe-write.sh" % day_tag)
