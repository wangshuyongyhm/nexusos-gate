"""检查类型: done_ack — done 总结强制消费闸（Task 1384，用户定向 0917）。

背景：1382 总结里的 SSH 密码失联预警被主控漏看，险些服务器全单停摆——
总结全文躺 task_state 无强制消费动作。机制化：
  dispatch gate D9（REJECT）：窗口内存在 DONE 且未 ack 的任务 → 拦派单；
  persist gate P17（WARN）：同一查询 → 落盘时提醒补 ack。
ack 动作：POST /task/{id}/ack {"agent":..., "key_points":["复述要点",...]}。

数据源：优先进程内 import nexusos_xdr.task_state（gate 引擎随 xdr 进程跑，
零网络）；import 失败（引擎在非 xdr 进程）→ fail-open 放行留痕（同 D7 先例）。
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

    tasks = "；".join(
        "{}（{}→{}，done 于 {}）".format(
            t.get("task_id", "?"),
            t.get("caller", "?"),
            t.get("callee", t.get("source", "?")),
            str(t.get("finished") or "?")[:16],
        )
        for t in unacked[:6]
    )
    more = f"（另 {len(unacked) - 6} 个）" if len(unacked) > 6 else ""
    return False, (
        f"{len(unacked)} 个 DONE 任务总结未消费（{via}，窗口 {window:g}h）：{tasks}{more}。"
        "先读总结复述要点再 ack：curl -X POST http://127.0.0.1:19998/task/<task_id>/ack "
        "-d '{\"agent\":\"<你的名>\",\"key_points\":[\"复述要点\"]}'"
    )
