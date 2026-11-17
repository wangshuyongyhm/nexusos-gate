"""P18 outcome_backfill — 主控套用经验 outcome 回填检查（Task1951 G3=清单 P4）.

口径（首期 WARN 观察一周，#464）：
- 当日该 agent 的 apply_attempt 行集合 A（agent_activity）
- apply_outcome 行 detail->>'apply_attempt_id' ∈ A 且 detail->>'result' != 'pending'
  → 计为已回填
- |A| - 已回填数 > 0 → WARN（套用未回填，经验永远 pending = 认知诚实失职）
- PG 不可达/无套用 → pass 附注（fail-open，WARN 级不阻塞）
"""
from __future__ import annotations


def check(params: dict, context: dict, agent: str) -> tuple:
    if not agent:
        return True, "P18: 无 agent 参数——skip"
    try:
        import psycopg2
        conn = psycopg2.connect("dbname=nexus_mem")
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM agent_activity "
            "WHERE action='apply_attempt' AND agent_id=%s AND created::date=CURRENT_DATE",
            (agent,))
        attempt_ids = [r[0] for r in cur.fetchall()]
        if not attempt_ids:
            cur.close(); conn.close()
            return True, "P18: 当日无 apply_attempt——无需回填"
        cur.execute(
            "SELECT detail->>'apply_attempt_id' FROM agent_activity "
            "WHERE action='apply_outcome' AND created::date >= CURRENT_DATE - 1 "
            "AND detail->>'result' <> 'pending' "
            "AND detail->>'apply_attempt_id' = ANY(%s)",
            ([str(i) for i in attempt_ids],))
        backfilled = {r[0] for r in cur.fetchall()}
        cur.close(); conn.close()
    except Exception as e:
        return True, "P18: PG 不可达（%s）——fail-open pass" % str(e)[:80]

    missing = len(attempt_ids) - len(backfilled)
    if missing > 0:
        return False, ("P18 outcome 回填: 当日 %d 条 apply_attempt，已回填 %d——"
                       "%d 条未回填（B5 用完经验回填 outcome，防经验永远 pending）"
                       % (len(attempt_ids), len(backfilled), missing))
    return True, ("P18: 当日 %d 条套用全部有 outcome 回填" % len(attempt_ids))
