#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""persist_pool_ledger.py — Task1879-B：persist 场景 WARN 产生即入池 + pass 自动销账。

机制（池 #352 用户裁定 B）：
  1. persist gate 结果含 fail 且 severity=WARN 的项 → 在 06-Memory/未决问题池.md
     「gate 自动登记」段追加一行（编号走 pool-next-id.sh 原子取号 + --check 防占）。
  2. 同 agent + 同 tag + 同关键（目录/项名）已有未闭环行 → 不重复登记。
  3. 后续 persist 同项 pass 时 → 池内该 agent 该项的未闭环行自动标闭环
     （状态 待办→✅，备注追加自动闭环注记；P4 额外要求目录 ∈ 本次 touched_dirs）。

写入纪律（池 #124 前科）：
  - 登记=行级追加（open('a')），禁全文重写；
  - 销账必须改已有行，采用「读行→只动目标行→临时文件原子 rename」，并加 flock 串行化。

gate_engine.check() 在 persist 场景结果汇总后调用 sync()（fail-open）。
"""
import fcntl
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

POOL_REL = os.path.join("06-Memory", "未决问题池.md")
SECTION_HEADER = "## gate 自动登记（persist 台账，Task1879-B）"
TABLE_HEADER = ("| # | 问题 | 类型 | 提出时间 | 提出会话 | 状态 | 备注 |\n"
                "|---|------|------|----------|----------|------|------|\n")
OPEN_STATUS = "待办"
LOCK_NAME = ".pool-ledger.lock"


def _next_id_script(vault_root: str) -> Path:
    """取号脚本定位（1959 单3 参数化）：

    env NEXUS_POOL_NEXT_ID_SCRIPT（支持 ${NEXUS_VAULT_ROOT}/${NEXUS_HOME} 占位）
    > vault 布局组合路径（私人深链默认，示例配置见 etc/checks/examples/）。
    不存在由 _next_id 调用方 skip（fail-open WARN，不炸 sync）。
    """
    explicit = os.environ.get("NEXUS_POOL_NEXT_ID_SCRIPT", "").strip()
    if explicit:
        import nexusos_common as _nxc
        return Path(_nxc.expand_env(explicit))
    return Path(vault_root) / "05-System" / "自动化脚本" / "pool-next-id.sh"


def _pool_path(vault_root: str) -> Path:
    return Path(vault_root) / POOL_REL


def _next_id(vault_root: str) -> int:
    """pool-next-id.sh 原子取号 + --check 防占（被占重取一次）。脚本缺失 → ValueError 由调用方转 skip。"""
    script = _next_id_script(vault_root)
    if not script.is_file():
        raise ValueError(f"pool-next-id 脚本不可用: {script}（env NEXUS_POOL_NEXT_ID_SCRIPT 可直指）")
    env = dict(os.environ, NEXUS_VAULT_ROOT=vault_root)
    for _ in range(3):
        out = subprocess.run(["bash", str(script)], capture_output=True, text=True,
                             env=env, timeout=10)
        nid = int(out.stdout.strip())
        chk = subprocess.run(["bash", str(script), "--check", str(nid)],
                             capture_output=True, env=env, timeout=10)
        if chk.returncode == 0:
            return nid
    raise RuntimeError("pool-next-id 连续取到被占用号")


def _row(nid: int, tag: str, subject: str, agent: str, note: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    return f"| {nid} | {tag} {subject} | gate告警 | {today} | {agent}-gate | {OPEN_STATUS} | {note} |\n"


def _p4_dir_entries(detail: str) -> list:
    """把 P4 的 '…: d1: reason; d2: reason' detail 拆成 (dir, reason) 列表。"""
    entries = []
    body = detail.split(":", 1)[1] if ":" in detail else detail
    for seg in body.split(";"):
        seg = seg.strip()
        if not seg:
            continue
        d, _, reason = seg.partition(":")
        entries.append((d.strip(), reason.strip() or "README 待同步"))
    return entries


def _load_lines(pool: Path) -> list:
    if not pool.exists():
        return []
    return pool.read_text(encoding="utf-8").splitlines(keepends=True)


def _is_open_row_for(line: str, tag: str, key: str, agent: str) -> bool:
    return (line.startswith("|") and tag in line and key in line
            and f"| {OPEN_STATUS} |" in line and f"{agent}-gate" in line)


def _append_rows(pool: Path, rows: list):
    """行级追加（含段头补齐），flock 串行化。"""
    lock_path = pool.parent / LOCK_NAME
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = _load_lines(pool)
        need_header = not any(l.rstrip() == SECTION_HEADER for l in lines)
        with open(pool, "a", encoding="utf-8") as f:
            if need_header:
                if lines and lines[-1].strip():
                    f.write("\n")
                f.write(f"{SECTION_HEADER}\n\n{TABLE_HEADER}")
            for r in rows:
                f.write(r)
        fcntl.flock(lock, fcntl.LOCK_UN)


def _close_rows(pool: Path, tag: str, agent: str, keys: list) -> int:
    """把匹配 tag+agent+keys 的未闭环行标闭环（原子 rename 写回）。返回闭环行数。"""
    lock_path = pool.parent / LOCK_NAME
    closed = 0
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lines = _load_lines(pool)
        if not lines:
            fcntl.flock(lock, fcntl.LOCK_UN)
            return 0
        today = datetime.now().strftime("%Y-%m-%d")
        changed = False
        for i, line in enumerate(lines):
            if not (line.startswith("|") and tag in line
                    and f"| {OPEN_STATUS} |" in line and f"{agent}-gate" in line):
                continue
            if keys and not any(k in line for k in keys):
                continue
            lines[i] = (line.replace(f"| {OPEN_STATUS} |", "| ✅ |", 1).rstrip("\n")
                        + f"（{today} persist gate pass 自动闭环）\n")
            closed += 1
            changed = True
        if changed:
            fd, tmp = tempfile.mkstemp(dir=str(pool.parent), prefix=".pool-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp, pool)
        fcntl.flock(lock, fcntl.LOCK_UN)
    return closed


def sync(context: dict, result: dict, agent: str = "") -> dict:
    """persist gate 结果 → 池台账同步。返回 {registered: n, closed: n}（fail-open 由调用方保证）。"""
    vault_root = str(context.get("vault_root") or os.environ.get("NEXUS_VAULT_ROOT") or "")
    if not vault_root or not Path(vault_root).is_dir():
        return {"registered": 0, "closed": 0, "skip": "vault_root 不可用"}
    agent = agent or context.get("agent") or "unknown"
    pool = _pool_path(vault_root)
    pool.parent.mkdir(parents=True, exist_ok=True)
    try:
        _next_id(vault_root)  # 前置探测：脚本缺失 → 整体 skip WARN（1959 参数化）
    except ValueError as e:
        return {"registered": 0, "closed": 0, "skip": f"pool-next-id 不可用（{e}）——WARN skip"}

    lines = _load_lines(pool)
    registered = 0
    new_rows = []
    for r in result.get("failures", []):
        if r.get("status") != "fail" or r.get("severity") != "WARN":
            continue
        tag = f"[gate-{r.get('id', '?')}]"
        name = str(r.get("name", ""))
        detail = str(r.get("detail", ""))
        if r.get("id") == "P4":
            subjects = [(f"{d} README 待同步（{reason[:80]}）", d)
                        for d, reason in _p4_dir_entries(detail)] or \
                       [(f"{name}（{detail[:80]}）", name)]
        else:
            subjects = [(f"{name}（{detail[:80]}）", name)]
        for subject, key in subjects:
            if any(_is_open_row_for(l, tag, key, agent) for l in lines) or \
               any(_is_open_row_for(l, tag, key, agent) for l in new_rows):
                continue  # 去重：同 agent+同 tag+同 key 未闭环行已在池
            nid = _next_id(vault_root)
            new_rows.append(_row(nid, tag, subject, agent, "自动登记 by gate_engine"))
            registered += 1
    if new_rows:
        _append_rows(pool, new_rows)

    closed = 0
    touched = set(context.get("touched_dirs") or [])
    for r in result.get("failures", []):
        if r.get("status") != "pass":
            continue
        tag = f"[gate-{r.get('id', '?')}]"
        keys = list(touched) if r.get("id") == "P4" else []
        closed += _close_rows(pool, tag, agent, keys)
    return {"registered": registered, "closed": closed}


def check(params: dict, context: dict, agent: str) -> tuple:
    """nexusos.gate.checks 协议入口（1959 单3 示例化）。

    台账健康检查：vault/脚本不可得 → WARN skip（fail-open，与 sync 同口径）；
    可得 → 池文件存在性 + 未闭环行数报告（事实型，恒 pass，异常态由人工/其他
    check 处置）。示例启用配置见 etc/checks/examples/persist_pool_ledger.yaml。
    """
    vault_root = str(context.get("vault_root") or os.environ.get("NEXUS_VAULT_ROOT") or "")
    if not vault_root or not Path(vault_root).is_dir():
        return False, "persist_pool_ledger: vault_root 不可用（设 NEXUS_VAULT_ROOT）——WARN skip", "WARN"
    try:
        _next_id(vault_root)
    except ValueError as e:
        return False, f"persist_pool_ledger: {e}——WARN skip", "WARN"
    pool = _pool_path(vault_root)
    if not pool.is_file():
        return True, f"池文件未建（{POOL_REL} 首次 WARN 登记时自动创建）"
    open_rows = sum(1 for l in _load_lines(pool) if OPEN_STATUS in l)
    return True, f"池台账在位，未闭环 {open_rows} 行（gate 自动登记段）"


if __name__ == "__main__":
    # CLI 调试：python3 persist_pool_ledger.py '<result_json>' '<context_json>'
    import json
    _result = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {"failures": []}
    _context = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(sync(_context, _result, agent=os.environ.get("NEXUS_AGENT", "cli")))
