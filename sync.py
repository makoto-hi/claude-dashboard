"""board と Repsona の全件を取得して DB に upsert する。

ポイント：
- 取得前の order_status を prev_status に退避してから upsert する。
  これで detect.py が「前回受注ではなかったが今回は受注」を見つけられる。
- 一回の同期で全件取得するシンプル設計。件数が多くなったら差分取得に切り替える。
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from db import get_conn, init_db
from board_client import BoardClient
from repsona_client import RepsonaClient

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_board() -> int:
    client = BoardClient()
    conn = get_conn()
    count = 0
    try:
        now = _now_iso()
        for p in client.iter_projects():
            pid = p["id"]
            name = p.get("name", "")
            client_name = (p.get("client") or {}).get("name", "")
            status = str(p.get("order_status", ""))        # 整数をそのまま文字列化 e.g. "5"
            amount = int(float(p.get("total") or 0))       # "15000.0" → 15000
            updated_at = p.get("updated_at", "")
            estimate_date = p.get("estimate_date", "")     # "2026-05-21" 形式の日付
            invoice_dates = json.dumps(p.get("invoice_dates") or [])  # ["2026-06-30", ...]

            # 前回ステータスを退避してから更新
            cur = conn.execute(
                "SELECT order_status FROM board_projects WHERE id = ?", (pid,)
            )
            row = cur.fetchone()
            prev_status = row["order_status"] if row else None

            conn.execute(
                """
                INSERT INTO board_projects
                  (id, name, client_name, order_status, total_amount, updated_at, last_seen_at, prev_status, estimate_date, invoice_dates)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  client_name = excluded.client_name,
                  order_status = excluded.order_status,
                  total_amount = excluded.total_amount,
                  updated_at = excluded.updated_at,
                  last_seen_at = excluded.last_seen_at,
                  prev_status = ?,
                  estimate_date = excluded.estimate_date,
                  invoice_dates = excluded.invoice_dates
                """,
                (pid, name, client_name, status, amount, updated_at, now, prev_status, estimate_date, invoice_dates, prev_status),
            )
            count += 1
        conn.commit()
    finally:
        conn.close()
    log.info("Synced %d board projects", count)
    return count


def _ms_to_iso(ms: int | None) -> str:
    """Repsona の updatedAt（ミリ秒タイムスタンプ）を ISO 8601 文字列に変換。"""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def sync_repsona() -> int:
    client = RepsonaClient()
    conn = get_conn()
    count = 0
    try:
        now = _now_iso()
        now_ms = datetime.now(timezone.utc).timestamp() * 1000

        for p in client.iter_projects():
            pid_int = int(p["id"])
            pid = str(pid_int)
            # fullName が実業務名（例: "ARUTEGA_web"）、name は短縮キー（例: "project1"）
            name = p.get("fullName") or p.get("name", "")
            updated_at = _ms_to_iso(p.get("updatedAt"))

            total = done = overdue = 0
            groups: dict[str, dict] = {}  # 親タスク名 → {total, done, overdue}

            try:
                closed_ids = client.get_closed_status_ids(pid_int)
                tasks = list(client.iter_tasks(pid_int))

                for t in tasks:
                    if t.get("parent") is None:
                        continue  # ヘッダータスク自体は集計対象外
                    total += 1
                    status_id = t.get("status")
                    is_done = status_id in closed_ids
                    due_ms = t.get("dueDate")
                    is_overdue = bool(due_ms and due_ms < now_ms and not is_done)
                    if is_done:
                        done += 1
                    if is_overdue:
                        overdue += 1

                    # parents 配列から最上位（ルート）の親タスク名を取得
                    # 深くネストされたタスクも正しくグループ化できる
                    root_name = next(
                        (p["name"] for p in t.get("parents", []) if p.get("parent") is None),
                        "(未分類)",
                    )
                    gname = root_name
                    if gname not in groups:
                        groups[gname] = {"total": 0, "done": 0, "overdue": 0}
                    g = groups[gname]
                    g["total"] += 1
                    if is_done:
                        g["done"] += 1
                    if is_overdue:
                        g["overdue"] += 1

            except Exception as e:
                log.warning("task fetch failed for repsona project %s: %s", pid, e)

            conn.execute(
                """
                INSERT INTO repsona_projects
                  (id, name, task_total, task_done, task_overdue, updated_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  name = excluded.name,
                  task_total = excluded.task_total,
                  task_done = excluded.task_done,
                  task_overdue = excluded.task_overdue,
                  updated_at = excluded.updated_at,
                  last_seen_at = excluded.last_seen_at
                """,
                (pid, name, total, done, overdue, updated_at, now),
            )

            # 親タスク単位の進捗を repsona_task_groups へ保存
            # sync のたびに洗い替え
            conn.execute("DELETE FROM repsona_task_groups")
            for gname, g in groups.items():
                conn.execute(
                    """
                    INSERT INTO repsona_task_groups (group_name, task_total, task_done, task_overdue, last_seen_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (gname, g["total"], g["done"], g["overdue"], now),
                )
            count += 1
        conn.commit()
    finally:
        conn.close()
    log.info("Synced %d repsona projects", count)
    return count


def sync_all() -> tuple[int, int]:
    init_db()
    b = sync_board()
    r = sync_repsona()
    return b, r


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    b, r = sync_all()
    print(f"board: {b}, repsona: {r}")
