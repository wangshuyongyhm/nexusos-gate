#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pool_write_channel.py — 未决问题池统一写通道（#723 缺陷②，Task 2611110941）。

与 pool-safe-write.sh 同一机制的 Python 共享单元（锁 + 写后校验 + 写痕）：
  - mkdir 自旋锁 .pool-write.lockdir（与 shell 封装同名同目录 → 两路写者互斥互通）；
  - 写后按 wc -l 口径读回校验行数（append=旧+新，replace=新）；
  - 写痕追加 ~/.pool-write.log（P19 对账依赖，格式与 shell 封装逐字段一致）。

为什么不 subprocess 调 shell 封装：销账是「读→改→写」整段原子操作，shell 的
replace 模式无法把「读」纳入锁内（内容在拿锁前就备好），并发下会互吞行（池#102
前科）。故按任务书 §3 修法方向②，把同一锁+写痕机制抽成本共享单元，读和写同锁窗口。
"""
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

LOCKDIR_NAME = ".pool-write.lockdir"        # 与 pool-safe-write.sh 同名锁，互斥互通
TRACE_LOG = Path.home() / ".pool-write.log"  # P19 对账写痕（同 shell 封装）
LOCK_TIMEOUT_S = 5.0                         # 与 shell 封装 17×0.3s≈5s 同量级
SPIN_INTERVAL_S = 0.3


class PoolWriteConflict(RuntimeError):
    """池写锁超时或写后校验失败——调用方 fail-open 处置，不静默等待。"""


@contextmanager
def pool_write_lock(pool: Path, timeout_s: float = LOCK_TIMEOUT_S):
    """拿池写锁（mkdir 自旋，同 pool-safe-write.sh）。

    yield 前锁已到手；退出时只删自己 mkdir 成功的那个锁目录；
    超时抛 PoolWriteConflict（对应 shell 封装 exit 3 的 5s 冲突语义）。
    """
    lockdir = pool.parent / LOCKDIR_NAME
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            lockdir.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise PoolWriteConflict(
                    f"池写锁 {timeout_s}s 超时（{lockdir} 被另一写入方持有）")
            time.sleep(SPIN_INTERVAL_S)  # c2-allow: mkdir 自旋锁退避，对齐 pool-safe-write.sh 的 sleep 0.3 同款语义（非绕过型等待）
    try:
        yield lockdir
    finally:
        lockdir.rmdir()  # 只删自己创建的目录；进程被 kill 时与 shell 封装同款残留风险


def _line_count(text: str) -> int:
    """wc -l 口径：数换行符（尾行无换行不计），保证与 shell 封装校验一致。"""
    return text.count("\n")


def _append_trace(op: str, pool: Path, old: int, new: int, back: int):
    """写痕落 ~/.pool-write.log——P19 靠「当日日期前缀」对账，格式须与 shell 封装一致。"""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(TRACE_LOG, "a", encoding="utf-8") as f:
        f.write(f"{ts} {op} {pool} old={old} new={new} back={back}\n")


def commit_write(pool: Path, content: str, op: str):
    """在已持锁窗口内落盘 + 行数校验 + 写痕（op: append|replace）。

    append=行级追加（禁全文重写——池 #124 前科）；replace=同目录临时文件 +
    os.replace 原子换入。行数对不上抛 PoolWriteConflict（对应 shell 封装
    exit 4 校验失败语义），写痕只在成功后落。
    """
    if op not in ("append", "replace"):
        raise ValueError(f"op 必须是 append|replace，得到 {op}")
    old_text = pool.read_text(encoding="utf-8") if pool.exists() else ""
    if op == "append":
        with open(pool, "a", encoding="utf-8") as f:
            f.write(content)
    else:
        fd, tmp = tempfile.mkstemp(dir=str(pool.parent), prefix=".pool-write.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, pool)
    old_n, new_n = _line_count(old_text), _line_count(content)
    back = _line_count(pool.read_text(encoding="utf-8"))
    expect = old_n + new_n if op == "append" else new_n
    if back != expect:
        raise PoolWriteConflict(f"写后行数 {back} != 预期 {expect}（{op} {pool}）")
    _append_trace(op, pool, old_n, new_n, back)
