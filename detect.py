"""差分検知：前回ステータスが「受注」ではなく、今回「受注」になった案件を見つける。

受注を表す文字列はboardの設定によって「受注」「won」など揺れる可能性があるので、
WON_STATUSES に列挙して判定する。実環境のboardで使われている値に合わせて調整。
"""
from __future__ import annotations
from db import get_conn

# boardのorder_statusで「受注」を意味するもの（DB保存は整数を文字列化した値）
# 実環境の board ステータス: 5=受注済, 1/2/3=見積中, 8=見積中(除)=失注扱い
WON_STATUSES = {"5", "受注済"}


def find_newly_won() -> list[dict]:
    """前回 != 受注 かつ 今回 == 受注 の案件一覧を返す。

    まだ通知していない（notifications_sentにレコードがない）ものだけ。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT bp.id, bp.name, bp.client_name, bp.total_amount, bp.order_status, bp.prev_status
            FROM board_projects bp
            LEFT JOIN notifications_sent ns
              ON ns.board_project_id = bp.id AND ns.event_type = 'order_won'
            WHERE ns.board_project_id IS NULL
            """
        ).fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        prev = (r["prev_status"] or "").strip().lower()
        curr = (r["order_status"] or "").strip().lower()
        prev_won = any(w.lower() == prev for w in WON_STATUSES)
        curr_won = any(w.lower() == curr for w in WON_STATUSES)
        if curr_won and not prev_won:
            result.append(dict(r))
    return result


def mark_notified(board_project_id: int, event_type: str = "order_won") -> None:
    from datetime import datetime, timezone
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO notifications_sent (board_project_id, event_type, sent_at)
            VALUES (?, ?, ?)
            """,
            (board_project_id, event_type, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
