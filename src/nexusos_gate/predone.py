#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""predone — done 回调端预检 CLI（Task 1401-w1，P0-1 速赢）。

薄封装复用 gate_engine.check("done", ...) 本地评估——同一规则源（etc/gates/
done.yaml），零服务端改动。小弟 done 回调前自跑，把登记机械项错漏拦在提交前，
而不是打回重走全链（P90 重交间隔 57.5min）。

用法:
  python3 -m nexusos_gate.predone --task-dir /abs/task/NN-xx \
      [--auto-files] [--files f1,f2] [--summary "..."] \
      [--experiences-n N] [--agent NAME] [--payload draft.json] [--json]

context 组装（对齐 xdr bg-gate 组装处，键名以 done.yaml+插件实读为准）:
  task_id          ← 任务目录名（NN-xx 段）
  task_path        ← input/task.md（存在时），否则任务目录本身
  task_path_report ← output/report.md（存在时）
  files            ← --files / --auto-files（output/**/* + reproduce.sh，
                     转 Vault 相对路径——G1 files_exist 的解析基准）
  summary          ← --summary / --payload；缺省取 report.md 首个 TL;DR 行模拟
  experiences      ← --experiences-n N 个占位（G3 二选一：数组非空即过，
                     真实写入由 done 前 POST /knowledge 保证）
  source           ← --agent（G5 mem_queried 的 agent_field）

退出码: 0=无 REJECT 项（WARN 不拦）｜1=存在 REJECT 项｜2=用法/环境错误。
MEM DB 类检查（G3/G5/G10）直连 PG，插件各自 fail-open/fail-closed 语义不动；
本 CLI 不装 PASS、不改规则本体。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from nexusos_gate.gate_engine import check as gate_check
from nexusos_gate.gate_engine import _ensure_vault_root, _load_scenario

# FAIL 项修法速查（predone 增值层——仅提示，不改 done.yaml 规则语义）
FIX_HINTS = {
    "G1": "files[] 路径须相对 Vault 根且真实存在——重跑加 --auto-files 自动收集",
    "G2": "--summary 传 ≥10 字真实摘要（勿两字打发）",
    "G3": "done 回调 experiences[] 带 ≥1 条，或先 POST :11537/knowledge 写 MEM",
    "G4": "补 output/report.md 至 ≥30 行",
    "G5": "done 前 curl :11537/search 查过 MEM（带 agent_id 留痕）",
    "G6": "report 补齐任务书完成标准的执行步骤记录",
    "G7": "report 中 L3/L2 声明须附证据（命令输出/文件路径）",
    "G8": "L2 复杂度任务须在 report 标注验证等级+决策暴露块",
    "G9": "report 补方法论应用一句（方法论名+反例/根因）",
    "G10": "POST :11537/apply_outcome 回填套用过的经验 outcome",
    "G11": "修复产出 .md 内断链 [[...]]（路径限定或裸名可解析）",
    "G12": "report 尾部补 yaml 机读块（status/next_steps）",
    "G13": "写 05-System/Agent/<你>/经验与坑.md 当日条目",
    "G14": "任务书尾部补「## 产出登记」wikilink 覆盖任务目录全部 .md；task.dispatched.*.md 副本行纯文本留痕即可",
    "G15": "nexus-wt done <task> 先合回 main 再回调",
}

_TLDR_RE = re.compile(r"^\s*(?:>?\s*\**TL;DR\**\s*[:：]?\s*)(.+)$", re.M)


def _task_id_of(task_dir: Path) -> str:
    """task/1401-w1-predone → 1401-w1-predone（任务号段）。"""
    return task_dir.name


def _auto_files(task_dir: Path, vault_root: Path) -> list:
    """--auto-files：output/**/*（文件）+ reproduce.sh，转 Vault 相对路径。"""
    files = []
    out = task_dir / "output"
    if out.is_dir():
        files.extend(p for p in sorted(out.rglob("*")) if p.is_file())
    rep = task_dir / "reproduce.sh"
    if rep.is_file():
        files.append(rep)
    rels = []
    for p in files:
        try:
            rels.append(p.relative_to(vault_root).as_posix())
        except ValueError:
            rels.append(str(p))  # Vault 外产出（repo_root 域）留原路径给 G1 三级解析
    return rels


def _summary_from_report(report: Path) -> str:
    """缺省 summary：取 report 首个 TL;DR 行（预检模拟，输出会注明来源）。"""
    try:
        m = _TLDR_RE.search(report.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return ""


def build_context(args) -> tuple[dict, list]:
    """构建 done gate context。返回 (context, notes)——notes 为组装说明（人读）。"""
    task_dir = Path(args.task_dir).resolve()
    if not task_dir.is_dir():
        raise SystemExit(f"predone: 任务目录不存在: {task_dir}")

    # vault_root：与引擎同源解析（context 显式 > env > 包位推导）
    cfg = _load_scenario("done")
    probe = {}
    err = _ensure_vault_root(cfg, probe)
    if err:
        raise SystemExit(f"predone: {err}")
    vault_root = Path(probe["vault_root"])

    task_md = task_dir / "input" / "task.md"
    report = task_dir / "output" / "report.md"

    if args.payload:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    else:
        payload = {}

    notes = []
    files = payload.get("files")
    if files is None:
        if args.files is not None:
            files = [f.strip() for f in args.files.split(",") if f.strip()]
        elif args.auto_files:
            files = _auto_files(task_dir, vault_root)
            notes.append(f"files: --auto-files 收集 {len(files)} 个（output/** + reproduce.sh）")
        else:
            files = []
    summary = args.summary or payload.get("summary") or ""
    summary_src = "--summary"
    if not summary and report.is_file():
        summary = _summary_from_report(report)
        summary_src = "report TL;DR 模拟"
    notes.append(f"summary 来源: {summary_src}")

    experiences = payload.get("experiences")
    if experiences is None:
        experiences = [{"title": "占位"} for _ in range(args.experiences_n)]
        if args.experiences_n:
            notes.append(f"experiences: {args.experiences_n} 个占位（G3 只验非空，"
                         "真实写入靠 done 前 POST /knowledge）")

    context = {
        "task_id": payload.get("task_id") or _task_id_of(task_dir),
        "task_path": str(task_md) if task_md.is_file() else str(task_dir),
        "task_path_report": str(report) if report.is_file() else "",
        "files": files,
        "summary": summary,
        "experiences": experiences,
        "source": args.agent,
        "vault_root": str(vault_root),
    }
    return context, notes


def run(args) -> int:
    context, notes = build_context(args)
    result = gate_check("done", context, agent=args.agent)

    rows = result.get("failures", [])
    hard = {r.get("id") for r in result.get("hard_fails", [])}
    warns = {r.get("id") for r in result.get("warns", [])}

    print("predone — done 回调预检（规则源 etc/gates/done.yaml，本地评估）")
    for n in notes:
        print(f"  · {n}")
    print("-" * 72)
    for r in rows:
        rid, name = r.get("id", "?"), r.get("name", "")
        status = r.get("status", "?")
        sev = r.get("severity", "")
        if status == "pass":
            mark, tag = "PASS", ""
        elif rid in hard:
            mark, tag = "FAIL", " REJECT"
        elif rid in warns:
            mark, tag = "WARN", ""
        else:
            mark, tag = status.upper(), f" {sev}"
        detail = str(r.get("detail", "")).replace("\n", " ")[:150]
        print(f"[{mark:>4}]{tag} {rid} {name}: {detail}")
        if mark == "FAIL":
            hint = FIX_HINTS.get(rid, "按 done.yaml 该项语义修复")
            print(f"       ↳ 修法: {hint}")
    print("-" * 72)
    n_hard, n_warn = len(hard), len(warns)
    verdict = "可提交（done 回调预期一次过）" if result.get("passed") else \
        f"存在 {n_hard} 个 REJECT 项——修复后再 done（WARN {n_warn} 项不拦）"
    print(f"结论: {'✅' if result.get('passed') else '❌'} {verdict}")

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result.get("passed") else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m nexusos_gate.predone",
        description="done 回调端预检——提交前本地跑 done gate，砍首过失败")
    ap.add_argument("--task-dir", required=True, help="任务目录绝对路径")
    ap.add_argument("--auto-files", action="store_true",
                    help="自动收集 output/**/* + reproduce.sh 为 files[]")
    ap.add_argument("--files", help="逗号分隔 files 列表（相对 Vault 根）")
    ap.add_argument("--summary", help="完成摘要（缺省取 report TL;DR 模拟）")
    ap.add_argument("--experiences-n", type=int, default=1,
                    help="experiences 占位数（默认 1；G3 只验非空）")
    ap.add_argument("--agent", default="nexus", help="调用方 agent 名（默认 nexus）")
    ap.add_argument("--payload", help="done 回调草案 JSON（优先于各散参）")
    ap.add_argument("--json", action="store_true", help="附打印原始 gate 结果")
    args = ap.parse_args(argv)
    try:
        return run(args)
    except SystemExit as e:
        print(f"predone: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
