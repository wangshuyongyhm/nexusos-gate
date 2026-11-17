"""检查类型: done_ack — done 总结强制消费闸（Task 1384，用户定向 0917）。

背景：1382 总结里的 SSH 密码失联预警被主控漏看，险些服务器全单停摆——
总结全文躺 task_state 无强制消费动作。机制化：
  dispatch gate D9（REJECT）：窗口内存在 DONE 且未 ack 的任务 → 拦派单；
  persist gate P17（WARN）：同一查询 → 落盘时提醒补 ack。
ack 动作：POST /task/{id}/ack {"agent":..., "key_points":["复述要点",...]}。

数据源：优先进程内 import nexusos_xdr.task_state（gate 引擎随 xdr 进程跑，
零网络）；import 失败（引擎在非 xdr 进程）→ fail-open 放行留痕（同 D7 先例）。

语义（B3 / 池 #826③ 裁定，2026-11-17）：**消费义务跟 caller 走**。
  - dispatch D9：只算「本次派单方（context.caller/agent）自己派出的未 ack 单」。
    别的 Agent 派给同一 callee 的未 ack 单不拦新派单——今晚实证：B1a 复测用同一
    callee 触发 D9 fail，实际那条欠账是本方（主控）还没消费的旧单，与本次派单无关。
  - persist P17：落盘上下文没有 caller 身份（required_context 无 agent），沿用
    全量口径——落盘提醒是「你自己该清的账」，不需要 caller 过滤。
"""
import os


def check(params: dict, context: dict, agent: str) -> tuple:
    """
    params: {window_hours: 24}
    返回: (passed, detail)
    """
    try:
        window = float((params or {}).get("window_hours", 24))
    except (TypeError, ValueError):
        window = 24.0

    try:
        from nexusos_xdr import task_state as _ts

        unacked = _ts.list_unacked(hours=window)
        via = "direct"
    except Exception as e:  # noqa: BLE001 — fail-open（gate 不因自身环境瘫痪派单）
        return True, (
            f"[fail-open] task_state 不可达（{type(e).__name__}: {str(e)[:60]}）"
            "——done_ack 无法核验，放行留痕（D7 同款先例）"
        )

    if not unacked:
        return True, f"窗口 {window:g}h 内 DONE 任务已全部 ack（{via}）"

    # 池 #826③：消费义务跟 caller 走——只计较本派单方自己派出的未 ack 单。
    # dispatcher 取 context.caller > context.agent > 调用方 agent（dispatch 场景三者
    # 通常同源）；全空（persist P17）→ 不过滤，保留"落盘提醒本人清账"的旧语义。
    dispatcher = str(context.get("caller") or context.get("agent") or agent or "").strip()
    if dispatcher:
        mine = [t for t in unacked if str(t.get("caller") or "").strip() == dispatcher]
        others = len(unacked) - len(mine)
    else:
        mine, others = unacked, 0

    others_note = f"（另有 {others} 条属其他派单方的待消费单，不计入本派单）" if others else ""
    if not mine:
        return True, (
            f"本派单方 {dispatcher!r} 窗口 {window:g}h 内 DONE 任务已全部 ack（{via}）{others_note}"
        )

    tasks = "；".join(
        "{}（{}→{}，done 于 {}）".format(
            t.get("task_id", "?"),
            t.get("caller", "?"),
            t.get("callee", t.get("source", "?")),
            str(t.get("finished") or "?")[:16],
        )
        for t in mine[:6]
    )
    more = f"（另 {len(mine) - 6} 个）" if len(mine) > 6 else ""
    scope = f"本派单方 {dispatcher!r} 名下" if dispatcher else "窗口内"
    return False, (
        f"{len(mine)} 个{scope} DONE 任务总结未消费（{via}，窗口 {window:g}h）：{tasks}{more}{others_note}。"
        "先读总结复述要点再 ack：curl -X POST http://127.0.0.1:19998/task/<task_id>/ack "
        "-d '{\"agent\":\"<你的名>\",\"key_points\":[\"复述要点\"]}'"
    )
