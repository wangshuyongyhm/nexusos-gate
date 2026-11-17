#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""persist_pool_ledger.py — Task1879-B：persist 场景 WARN 产生即入池 + pass 自动销账。

机制（池 #352 用户裁定 B）：
  1. persist gate 结果含 fail 且 severity=WARN 的项 → 在 06-Memory/未决问题池.md
     「gate 自动登记」段追加一行（编号走 pool-next-id.sh 原子取号 + --check 防占）。
  2. 同 tag + 同关键（目录/项名）已有未闭环 gate 行 → 不重复登记（#723 起跨 agent 去重）。
  3. 后续任意 agent persist 同项 pass 时 → 池内同 tag+关键 的未闭环 gate 行自动标闭环
     （状态 待办→✅，备注追加自动闭环注记；P4 额外要求目录 ∈ 本次 touched_dirs）。
     人工行/非 gate 告警行类型列不是 gate告警，不会被误闭环（#723 缺陷③放宽判据）。

写入纪律（池 #124 前科 + #723 统一通道）：
  - 登记与销账全部走 pool_write_channel（= pool-safe-write.sh 同款 .pool-write.lockdir
    mkdir 锁 + 写后行数校验 + ~/.pool-write.log 写痕），锁只此一把，不再 flock 旁路直写；
  - 登记=行级追加，销账=锁窗口内「读行→只动目标行→原子 replace」（并发不互吞行）。

gate_engine.check() 在 persist 场景结果汇总后调用 sync()（fail-open）。
"""
import os
import subprocess
import sys

from datetime import datetime
from pathlib import Path

from nexusos_gate import pool_write_channel

POOL_REL = os.path.join("06-Memory", "未决问题池.md")
SECTION_HEADER = "## gate 自动登记（persist 台账，Task1879-B）"
TABLE_HEADER = ("| # | 问题 | 类型 | 提出时间 | 提出会话 | 状态 | 备注 |\n"
                "|---|------|------|----------|----------|------|------|\n")
OPEN_STATUS = "待办"
GATE_ROW_TYPE = "| gate告警 |"  # gate 自动登记行的类型列专属标记（#723 闭环判据：防误闭环人工行）


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


def _is_open_row_for(line: str, tag: str, keys: list = None) -> bool:
    """未闭环 gate 行判据（#723 缺陷③：放宽为跨 agent）。

    行首 | + 同 tag + 待办 + 类型列=gate告警；keys 非空时还要求行内含任一 key
    （P4 的目录锚定）。登记行「提出会话=<agent>-gate」只作溯源，不再参与判定——
    登记 Agent 收工后其他 Agent 的 pass 也能闭环其遗留行（池#706/#707/#710
    三行人工收口的根因）。人工行/普通问题行类型列不是 gate告警，天然不匹配。
    """
    if not (line.startswith("|") and tag in line
            and f"| {OPEN_STATUS} |" in line and GATE_ROW_TYPE in line):
        return False
    return not keys or any(k in line for k in keys)


def _append_rows(pool: Path, rows: list):
    """登记=行级追加（含段头补齐），写走统一通道（#723 缺陷②）。

    持 .pool-write.lockdir（与 pool-safe-write.sh 互斥互通）+ 写后校验 +
    ~/.pool-write.log 写痕——P19 对账自然通过，gate 不再自触发 WARN（池#710）。
    """
    with pool_write_channel.pool_write_lock(pool):
        lines = _load_lines(pool)
        buf = []
        if not any(l.rstrip() == SECTION_HEADER for l in lines):
            if lines and lines[-1].strip():
                buf.append("\n")
            buf.append(f"{SECTION_HEADER}\n\n{TABLE_HEADER}")
        buf.extend(rows)
        pool_write_channel.commit_write(pool, "".join(buf), "append")


def _close_rows(pool: Path, tag: str, keys: list) -> int:
    """把匹配 tag+keys 的未闭环 gate 行标闭环（跨 agent，#723 缺陷③）。

    「读→改→写」整段在统一通道锁窗口内完成（并发互关不互吞行，#723 缺陷②），
    replace 落盘带写痕。返回闭环行数。
    """
    closed = 0
    with pool_write_channel.pool_write_lock(pool):
        lines = _load_lines(pool)
        today = datetime.now().strftime("%Y-%m-%d")
        for i, line in enumerate(lines):
            if not _is_open_row_for(line, tag, keys):
                continue
            lines[i] = (line.replace(f"| {OPEN_STATUS} |", "| ✅ |", 1).rstrip("\n")
                        + f"（{today} persist gate pass 自动闭环）\n")
            closed += 1
        if closed:
            pool_write_channel.commit_write(pool, "".join(lines), "replace")
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
            if any(_is_open_row_for(l, tag, [key]) for l in lines) or \
               any(_is_open_row_for(l, tag, [key]) for l in new_rows):
                continue  # 去重：同 tag+同 key 未闭环 gate 行已在池（跨 agent，#723）
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
        closed += _close_rows(pool, tag, keys)
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
    # CLI 调试：python3 persist_pool_ledger.py '<result_json>' '<context_json>' [--agent <name>]
    # B6（MEM#95841 同族）：本入口也是 agent 身份消费点——复用引擎的单点解析
    # （NEXUS_AGENT env > --agent > cli），不再自带一份 env 兜底（防两处优先级漂移）。
    import json
    from nexusos_gate.gate_engine import _resolve_cli_agent
    _agent, _argv = _resolve_cli_agent(sys.argv[1:])
    _result = json.loads(_argv[0]) if len(_argv) > 0 else {"failures": []}
    _context = json.loads(_argv[1]) if len(_argv) > 1 else {}
    print(sync(_context, _result, agent=_agent))
