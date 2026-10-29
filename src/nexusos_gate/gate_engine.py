#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_engine.py — NEXUS Gate 声明式门禁引擎(调度核心)。

只做 4 件事,永远不因新场景/新检查而修改:
  1. 加载场景 YAML
  2. 校验 required_context 齐全
  3. 按检查 type 分发到 _checks/ 插件 + 汇总 pass/fail + 分级
  4. 进场景前自动解析注入 vault_root(Task696 自 format,裸调治本)

检查逻辑独立成 etc/gates/_checks/*.py 插件(启动时自动发现)。

Task630 首包化: 正源自 nexusos_xdr/gate_engine.py 迁入(旧位留 re-export shim)。
插件发现改用包绝对路径 nexusos_gate.etc.gates._checks.*(不再依赖 sys.path hack)。
"""
import importlib
import importlib.metadata
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import nexusos_common as _nxc

try:
    import yaml
except ImportError:
    sys.exit("pyyaml 未安装,gate_engine 无法工作")

ENGINE_DIR = Path(__file__).resolve().parent
# Task679 拍板 A: env 可覆盖场景目录——OSS 包内 etc/gates 只含通用插件池
# （NEXUS 自用场景不随包），用户经 NEXUS_GATES_DIR 指向自己的场景目录
# （examples/gates 即可用）。本机不设 env 时行为不变（包内路径）。
GATES_DIR = Path(os.environ.get("NEXUS_GATES_DIR") or (ENGINE_DIR / "etc" / "gates"))
# Task679 拍板 A: 插件池恒在包内（通用插件随包）——env 只覆盖场景目录；
# 外置场景引用的检查类型仍从包内 _checks 解析。
CHECKS_DIR = ENGINE_DIR / "etc" / "gates" / "_checks"

# Task1704 件二（池#286）：gate WARN 落盘观测的聚合计时缓存——同
# (scenario, warn 集) 窗口内只发 1 条 gate_warn 事件（进程内单源）。
_GATE_WARN_WINDOW_SEC = float(os.environ.get("NEXUS_GATE_WARN_WINDOW", "600"))
_WARN_EMIT_CACHE: dict = {}


def _plugin_warn_agent() -> str:
    """插件告警事件的归因名（Task1561 / 1547-F6）。

    原 hardcoded 'nexusos-gate' 未注册 agents 表 → 9334 行归因断层。
    统一走 NEXUS_AGENT env 链（hook/dispatchd 侧同款：env > nexus 兜底，
    兜底名是注册名，B12/归因统计不再失明）。
    """
    return os.environ.get("NEXUS_AGENT") or "nexus"


def _log_gate_plugin_warn(plugin_name: str, reason: str):
    """插件加载告警写 PG agent_activity（让 monitor 能发现死插件）。fail-open。"""
    try:
        import psycopg2
        conn = psycopg2.connect(dbname="nexus_mem")
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO agent_activity (agent_id, action, target_type, detail)
            VALUES (%s, 'gate_plugin_warn', 'gate_plugin', %s)
        """, (_plugin_warn_agent(), json.dumps({"plugin": plugin_name, "reason": reason}, ensure_ascii=False),))
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # fail-open：PG 写失败不影响 gate 运行


def _load_check_plugins() -> dict:
    """启动时扫描 _checks/,自动加载所有检查插件。
    文件名 = 检查类型名(如 field_check.py → type: field_check)。
    每个插件必须导出 check(params, context, agent) -> (bool, str) 函数。
    """
    plugins = {}
    if not CHECKS_DIR.exists():
        return plugins
    for f in sorted(CHECKS_DIR.glob("*.py")):
        # Task1561 (1547-F6 告警风暴根因): test_* / *_test 是测试文件非插件——
        # 原当插件候选扫描→每次 import 告警 4-5 条（PG 实证 ~220/天 × 9334 行）。
        # 与 "_" 前缀同款豁免约定（C5 的 test 判定同款形态）。
        if f.name.startswith("_") or f.name.startswith("test_") or f.name.endswith("_test.py"):
            continue
        try:
            # 包绝对路径 import(Task630 迁包后不再依赖 sys.path hack):
            # nexusos_gate.etc.gates._checks.field_check
            mod_name = f"nexusos_gate.etc.gates._checks.{f.stem}"
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "check") and callable(mod.check):
                plugins[f.stem] = mod.check
            else:
                # 插件未导出 check 函数,跳过(记 stderr 不崩) + 写 PG 告警(让 monitor 发现)
                print(f"[gate_engine] 插件 {f.name} 未导出 check 函数,跳过", file=sys.stderr)
                _log_gate_plugin_warn(f.name, "未导出 check 函数")
        except Exception as e:
            # 插件加载失败,记 WARN 跳过(不崩 engine) + 写 PG 告警(让 monitor 发现)
            print(f"[gate_engine] 插件 {f.name} 加载失败: {e},跳过", file=sys.stderr)
            _log_gate_plugin_warn(f.name, f"加载失败: {e}")
    return plugins


def _load_entry_point_checks() -> dict:
    """nexusos.gate.checks 插件协议（1959 单3，design §5）：entry_points 组注入。

    - 稳定序：sorted(name)（任务书陷阱1——防 check 集合随安装顺序漂移）
    - 单条失败跳过不炸引擎（与目录扫描同款 fail-open + PG 告警）
    - 加载物须导出可调用 check(params, context, agent)；模块路径或 "mod:attr" 均可
    """
    plugins = {}
    try:
        eps = importlib.metadata.entry_points(group="nexusos.gate.checks")
    except Exception:
        return plugins
    for ep in sorted(eps, key=lambda e: e.name):
        try:
            loaded = ep.load()
            fn = loaded if callable(loaded) else getattr(loaded, "check", None)
            if callable(fn):
                plugins[ep.name] = fn
            else:
                print(f"[gate_engine] entry_point {ep.name} 未导出 check，跳过", file=sys.stderr)
                _log_gate_plugin_warn(f"entry_point:{ep.name}", "未导出 check 函数")
        except Exception as e:
            print(f"[gate_engine] entry_point {ep.name} 加载失败: {e}，跳过", file=sys.stderr)
            _log_gate_plugin_warn(f"entry_point:{ep.name}", f"加载失败: {e}")
    return plugins


def _load_user_checks_d() -> dict:
    """$NEXUS_HOME/gate/checks.d/*.yaml 用户声明式启用（1959 单3，design §5）。

    每文件结构：{scenario: <场景名>, items: [<check item>...]}——items 追加进
    对应场景（不改内置 items）。文件名 sorted 稳定序；解析失败单文件跳过
    （fail-open，stderr 记录）。NEXUS_HOME 解析单源 nexusos-common。
    """
    out: dict = {}
    d = _nxc.subpath("gate", "checks.d")
    try:
        if not d.is_dir():
            return out
        for f in sorted(d.glob("*.yaml")):
            try:
                cfg = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            except Exception as e:
                print(f"[gate_engine] checks.d/{f.name} 解析失败: {e}，跳过", file=sys.stderr)
                continue
            scenario = cfg.get("scenario", "")
            items = cfg.get("items", [])
            if scenario and isinstance(items, list) and items:
                out.setdefault(scenario, []).extend(items)
    except Exception:
        pass
    return out


# 启动时加载一次：entry_points 协议（外部注入+包内五私人 check）∪ 包内目录扫描
# （内置权威——同键时目录扫描覆盖 entry_points，外部新名正常注入）。
CHECK_PLUGINS = {**_load_entry_point_checks(), **_load_check_plugins()}
# 用户 checks.d 场景追加项（$NEXUS_HOME/gate/checks.d/*.yaml）——按需懒读后缓存。
_USER_CHECKS_D_CACHE: dict = {}


def _load_scenario(scenario: str) -> dict:
    """加载场景 YAML。返回配置 dict。

    1959 单3：加载后追加用户 checks.d 声明式 items（$NEXUS_HOME/gate/
    checks.d/*.yaml 的 {scenario, items}）——不改内置 items，只增不改。
    """
    yaml_path = GATES_DIR / f"{scenario}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"场景 YAML 不存在: {yaml_path}")
    with open(yaml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not _USER_CHECKS_D_CACHE:
        _USER_CHECKS_D_CACHE.update(_load_user_checks_d() or {"": []})
    extra_items = _USER_CHECKS_D_CACHE.get(scenario) or []
    if extra_items:
        cfg = dict(cfg or {})
        cfg["items"] = list((cfg or {}).get("items", [])) + list(extra_items)
    return cfg


def _validate_context(required: list, context: dict) -> list:
    """校验 required_context 是否齐全。返回缺失字段名列表。

    Task538 修复7: required 检查"key 存在"而非"值非空"——pre-commit hook 故意
    传 commit_msg=''（-m 模式 COMMIT_EDITMSG 未写入），P-g4 的空串视为缺失会
    拦截所有 commit。空字符串/0/False 都算"已提供"（只是空值）。
    None 视为缺失（显式传 None = 没提供）。
    """
    missing = []
    for item in required:
        name = item.get("name", "") if isinstance(item, dict) else str(item)
        is_required = item.get("required", True) if isinstance(item, dict) else True
        if is_required:
            if name not in context or context.get(name) is None:
                missing.append(name)
    return missing


def _resolve_template(value: Any, context: dict) -> Any:
    """递归解析 context 占位符({var})。支持 str/list/dict。

    衔接性修复(2026-07-29): except 补 ValueError。
    原只接 KeyError/IndexError,但 str.format 遇到非法字段名(如 shell 的
    ${VAR:-default} 被 format 当字段名 PROJECT_ROOT:-. 解析)会抛 ValueError,
    导致整个 check 崩溃。补 ValueError 让它和 KeyError 一样静默返回原串。
    """
    if isinstance(value, str):
        try:
            return value.format(**context)
        except (KeyError, IndexError, ValueError):
            return value
    elif isinstance(value, list):
        return [_resolve_template(v, context) for v in value]
    elif isinstance(value, dict):
        return {k: _resolve_template(v, context) for k, v in value.items()}
    return value


def _ensure_vault_root(cfg: dict, context: dict):
    """Task696 引擎自 format:vault_root 缺省时自动解析注入(治裸调 bad substitution)。

    与 nexusos_xdr._vault_env.resolve_gate_vault_root 同语义(1957 起锚点解析
    单源=nexusos-common,两处仅保留各自的缺 vault 策略):
    context 显式值 > env NEXUS_VAULT_ROOT > 包位置推导(common 哨兵)。
    场景不含 {vault_root} 模板时不强制——OSS 通用场景无 vault 也能跑。

    Returns:
        None: 注入成功,或场景不需要 vault_root
        str: 解析失败的人话错误(调用方 fail-fast 返回,绝不带字面量进 check
             ——_resolve_template 对缺 key 静默留原串,cwd/路径会变非法)
    """
    vr = str(context.get("vault_root") or os.environ.get("NEXUS_VAULT_ROOT") or "")
    if not vr:
        # 1957 锚点单源：哨兵推导收敛 nexusos-common（原 parents[3] 内联推导删除）
        auto_dir = _nxc.auto_scripts_dir(ENGINE_DIR)
        if auto_dir is not None:
            vr = str(auto_dir.parents[1])
    if not vr or "{" in vr or not Path(vr).is_dir():
        if "{vault_root}" not in repr(cfg):
            return None  # 场景不用 {vault_root}:不阻塞(OSS 通用场景)
        return (
            f"vault_root 不可用（解析值 {vr!r} 非存在目录）。gate YAML 已全量 "
            f"{{vault_root}} 模板化（T678），缺该 key 会静默落字面量致 cwd/路径"
            f"非法（bad substitution）——显式拒绝。设 NEXUS_VAULT_ROOT 或在 "
            f"context 传 vault_root"
        )
    context.setdefault("vault_root", vr)
    return None


# Task538 修复5: on_pass 钩子注册表（从 mcp_server 下沉到 engine）
# gate_engine.check() passed 后自动触发——CLI/其他 caller 也受益
_ON_PASS_HOOKS: dict = {}  # {scenario: callback(scenario, context, result)->None}


def register_on_pass(scenario: str, callback) -> None:
    """注册 on_pass 钩子（模块加载时调，Task538 修复5）。"""
    _ON_PASS_HOOKS[scenario] = callback


def check(scenario: str, context: dict, agent: str = "") -> dict:
    """过场景门禁。返回 {passed, failures, hard_fails, warns}。

    Args:
        scenario: 场景名(done/init/dispatch/persist/code)
        context: Agent 传入的上下文(含 required_context 声明的字段)
        agent: 调用方 agent 名
    """
    context = context or {}
    # 1. 加载场景
    try:
        cfg = _load_scenario(scenario)
    except FileNotFoundError as e:
        return {"passed": False, "failures": [{"detail": str(e)}],
                "hard_fails": [{"detail": str(e)}], "warns": []}

    # 2. Task696 自 format:vault_root 自动解析注入(调用方契约下沉到引擎,
    #    裸调 from nexusos_xdr import gate_check 不再喂 vault_root 也能跑)
    vr_err = _ensure_vault_root(cfg, context)
    if vr_err:
        vr_item = {"id": "VR", "name": "vault_root 自解析", "status": "fail",
                   "severity": "REJECT", "detail": vr_err}
        return {"passed": False, "failures": [vr_item],
                "hard_fails": [vr_item], "warns": []}

    # 3. 校验 required_context
    missing = _validate_context(cfg.get("required_context", []), context)
    if missing:
        msg = f"缺 context 字段: {missing}"
        return {"passed": False, "failures": [{"detail": msg}],
                "hard_fails": [{"detail": msg}], "warns": []}

    # 4. 逐项检查
    results = []
    for item in cfg.get("items", []):
        item_id = item.get("id", "?")
        item_name = item.get("name", item_id)
        severity = item.get("severity", "WARN")
        is_auto = item.get("auto", True)

        if not is_auto:
            # manual 项:只列 reminder
            results.append({
                "id": item_id, "name": item_name, "status": "manual",
                "severity": severity, "detail": item.get("reminder", "需人工确认")
            })
            continue

        check_cfg = item.get("check", {})
        check_type = check_cfg.get("type", "")
        # 解析占位符
        check_cfg = _resolve_template(check_cfg, context)

        check_fn = CHECK_PLUGINS.get(check_type)
        if check_fn is None:
            results.append({
                "id": item_id, "name": item_name, "status": "fail",
                "severity": "REJECT",  # 未知检查类型 = 硬拦(防配置错)
                "detail": f"未知检查类型: {check_type}(插件 {_checks_dir_rel()}/{check_type}.py 未加载)"
            })
            continue

        try:
            ret = check_fn(check_cfg, context, agent)
            # T670 协议: 插件可返回三元组 (passed, detail, severity_override)——
            # 跨目录重定向等"降 WARN 不 REJECT"场景（line_count G4）。二元组向后兼容。
            if isinstance(ret, tuple) and len(ret) == 3:
                passed, detail, _sev_override = ret
                if not passed and _sev_override in ("WARN", "REJECT"):
                    severity = _sev_override
            else:
                passed, detail = ret
        except Exception as e:
            passed, detail = False, f"检查插件异常: {type(e).__name__}: {str(e)[:100]}"

        results.append({
            "id": item_id, "name": item_name,
            "status": "pass" if passed else "fail",
            "severity": severity, "detail": detail
        })

    # 5. 汇总
    hard_fails = [r for r in results if r["status"] == "fail" and r["severity"] == "REJECT"]
    warns = [r for r in results if r["status"] == "fail" and r["severity"] == "WARN"]
    manual = [r for r in results if r["status"] == "manual"]
    result = {
        "passed": len(hard_fails) == 0,
        "failures": results,
        "hard_fails": hard_fails,
        "warns": warns,
        "manual": manual,
    }
    # Task1879-B（池#352 用户裁定）: persist 场景 WARN 产生即入池 + pass 自动销账。
    # 先只 persist 域（任务书禁止过度泛化到其他场景）。fail-open：台账失败不影响 gate 结果。
    if scenario == "persist":
        try:
            from nexusos_gate import persist_pool_ledger as _ppl
            _ledger = _ppl.sync(context, result, agent=agent or context.get("agent", ""))
            if _ledger.get("registered") or _ledger.get("closed"):
                result["pool_ledger"] = _ledger
        except Exception as _ple:
            print(f"[gate_engine] WARNING: persist 池台账同步失败（不阻断 gate 结果）: "
                  f"{type(_ple).__name__}: {_ple}", file=sys.stderr)
    # Task538 修复5: on_pass 钩子在 engine 层触发（CLI/其他 caller 也受益）
    if result["passed"]:
        _hook = _ON_PASS_HOOKS.get(scenario)
        if _hook:
            import logging
            try:
                _hook(scenario, context, result)
            except Exception as _he:
                logging.getLogger("nexusos_xdr.gate_engine").warning(
                    f"[on_pass] {scenario} 钩子失败（不阻断 gate 结果）: {_he}")

    # Task609 搭车②: 内置无条件事件登记（治 import 直调无痕迹断层，用户已同意）。
    # 局部 import 防环（依赖方向 session_state 不 import 本模块——已核实）。
    # detail 格式与 mcp_server.gate_check 工具的历史登记完全一致（M8 按格式解析）；
    # mcp_server 侧重复块已删（防双写）。fail-open：登记失败绝不影响 gate 结果。
    try:
        from nexusos_xdr import session_state as _ss
        _gate_agent = agent or context.get("agent") or context.get("source") \
            or context.get("caller") or "unknown"
        # T657 修1: 同任务同结果只发一次事件——治 648 实证的重扫放大
        # （patrol 预检 + callback bg-gate + agent 重试回调三源都会跑 done gate，
        # 每次无条件发事件 → 同秒爆发 38 条、唯一任务仅 17-18）。
        # key 含 passed+reject 集：fail→pass 变化是新 key 自然重发（恢复信号不丢）。
        # 非 done 场景/无 task_id 照发（dispatch/persist 等本就低频）。
        _emit_evt = True
        _tid657 = context.get("task_id") or ""
        if _tid657 and scenario == "done":
            try:
                from nexusos_xdr import task_state as _ts657
                _sig657 = "gate_event:%s:%s:%s" % (
                    scenario, result.get("passed"),
                    ",".join(sorted(str(r.get("id", "?")) for r in result.get("hard_fails", []))))
                _emit_evt = _ts657.once_flag(_tid657, _sig657)
            except Exception:
                _emit_evt = True  # 判重失败→保守发（宁可重复不可丢信号）
        if _emit_evt:
            _ss.append_event(
                agent=_gate_agent,
                event_type="gate_check",
                detail=f"scenario={scenario} passed={result.get('passed')} "
                       f"reject={[r.get('id', '?') for r in result.get('hard_fails', [])]} "
                       f"warn={[r.get('id', '?') for r in result.get('warns', [])]}",
                target=f"gate:{scenario}",
            )
        # Task1704 件二（池#286）：WARN 命中独立落 events——原 WARN 只回调用方
        # 不落盘，code 场景 3 周 262 次运行 WARN 零留存，「误报率」永远算不出。
        # 噪音控制：同 (scenario, warn 集) 短窗聚合计 1 条（模块级 TTL 缓存，
        # 进程内单源；窗口 env NEXUS_GATE_WARN_WINDOW 默认 600s），别刷爆 events。
        _warn_ids = sorted(str(r.get("id", "?")) for r in result.get("warns", []))
        if _warn_ids:
            _warn_key = f"{scenario}:{','.join(_warn_ids)}"
            _now_ts = time.time()
            _last = _WARN_EMIT_CACHE.get(_warn_key, 0.0)
            if _now_ts - _last >= _GATE_WARN_WINDOW_SEC:
                _WARN_EMIT_CACHE[_warn_key] = _now_ts
                _ss.append_event(
                    agent=_gate_agent,
                    event_type="gate_warn",
                    detail=f"scenario={scenario} warn={_warn_ids} "
                           f"hits={len(_warn_ids)} agent={_gate_agent}",
                    target=f"gate-warn:{scenario}",
                )
    except Exception as _e:
        # 1636 活③(1634 遗留): logging 无 handler 配置时 warning 被吞——补 stderr
        # 直打, "gate 事件未落流"大声可见(fail-open 语义不变: 检查主流程继续)
        import sys as _sys
        print(f"[gate_engine] WARNING: gate 事件未落流(GATE_GRACE 将看不到本次) "
              f"scenario={scenario} agent={agent}: {type(_e).__name__}: {_e}",
              file=_sys.stderr)
        import logging
        logging.getLogger("nexusos_xdr.gate_engine").warning(
            "[Task609] gate 事件写入失败 scenario=%s agent=%s: %s", scenario, agent, _e)
    return result


def _checks_dir_rel() -> str:
    """调试用:返回 _checks 相对路径。"""
    return str(CHECKS_DIR.relative_to(ENGINE_DIR))


if __name__ == "__main__":
    # CLI 调试入口:python3 gate_engine.py done '{"task_path":"...","files":[],...}'
    import json
    if len(sys.argv) < 2:
        print("用法: gate_engine.py <scenario> [context_json]")
        sys.exit(2)
    scenario = sys.argv[1]
    context = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    # T678b 修1: agent 读 NEXUS_AGENT env（默认 cli）——原硬编码 "cli" 未注册，
    # xdr 事件写入必败（MEM#62544①）→ state_transition_guard 的 60s 事件检查
    # 诚实路径永远无法满足。与 nexus-persist-commit.sh 同款语义。
    _cli_agent = os.environ.get("NEXUS_AGENT", "cli")
    # T678b 修1: CLI 不经 registry——vault_root 预注入复用 678 防线
    # （context > env NEXUS_VAULT_ROOT > 包位置推导；解析失败沿用其人话报错）
    try:
        from nexusos_xdr._vault_env import resolve_gate_vault_root
        _vr_ok, _vr = resolve_gate_vault_root(context)
        if not _vr_ok:
            print(json.dumps({"passed": False, "error": _vr}, ensure_ascii=False, indent=2))
            sys.exit(2)
    except ImportError:
        pass  # nexusos_xdr 不可达（纯 gate 包独立部署）——无注入场景照旧
    result = check(scenario, context, agent=_cli_agent)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["passed"] else 1)
