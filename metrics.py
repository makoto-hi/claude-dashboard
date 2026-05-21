"""DBから KPI を集計する。"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from db import get_conn
from detect import WON_STATUSES

# 平均人日単価: HTML/CSS ¥68,000-70,000, ディレクション ¥67,500 の中間値
AVG_DAILY_RATE = 68_000

# 8=見積中(除) は「失注扱い」として受注率の分母に含める
LOST_STATUSES = {"8", "見積中(除)"}


def _is_won(s: str | None) -> bool:
    if not s:
        return False
    return s.strip().lower() in {w.lower() for w in WON_STATUSES}


def _is_lost(s: str | None) -> bool:
    if not s:
        return False
    return s.strip().lower() in {w.lower() for w in LOST_STATUSES}


def _fiscal_year_range(year: int) -> tuple[str, str]:
    """年度の開始日・終了日を返す。例: 2026 → ('2026-03-01', '2027-02-28')"""
    import calendar
    end_day = calendar.monthrange(year + 1, 2)[1]  # 閏年対応
    return f"{year}-03-01", f"{year + 1}-02-{end_day:02d}"


def get_kpis(fiscal_year: int | None = None) -> dict:
    """受注率・請求状況・未マッチ・遅延タスクのサマリを返す。

    fiscal_year: 年度（例: 2026 → 2026/03/01〜2027/02/28）。None で全期間。
    """
    conn = get_conn()

    # 期フィルター条件（estimate_date ベース）
    if fiscal_year:
        period_start, period_end = _fiscal_year_range(fiscal_year)
        date_clause = "AND estimate_date >= ? AND estimate_date <= ? AND estimate_date IS NOT NULL"
        date_params: tuple = (period_start, period_end)
    else:
        date_clause = ""
        date_params = ()

    won_in = ",".join(f"'{w}'" for w in WON_STATUSES)
    lost_in = ",".join(f"'{l}'" for l in LOST_STATUSES)

    try:
        # 受注率（受注 / (受注 + 失注)）
        rows = conn.execute(
            f"SELECT order_status, COUNT(*) AS c FROM board_projects WHERE 1=1 {date_clause} GROUP BY order_status",
            date_params,
        ).fetchall()
        won = lost = active = 0
        for r in rows:
            if _is_won(r["order_status"]):
                won += r["c"]
            elif _is_lost(r["order_status"]):
                lost += r["c"]
            else:
                active += r["c"]
        denom = won + lost
        win_rate = (won / denom * 100) if denom else None

        # Repsona遅延タスク合計（期に関わらず全プロジェクト）
        overdue = conn.execute(
            "SELECT COALESCE(SUM(task_overdue), 0) AS s FROM repsona_projects"
        ).fetchone()["s"]

        # 未マッチ案件（受注済みなのにRepsonaと紐付いていない）
        # Repsonaグループ名が name または client_name に含まれていれば自動マッチとみなす
        group_names = [
            (r["group_name"] or "").lower()
            for r in conn.execute("SELECT group_name FROM repsona_task_groups").fetchall()
        ]
        group_names = [g for g in group_names if g]
        raw_unmatched = conn.execute(
            f"""
            SELECT bp.id, bp.name, bp.client_name, bp.estimate_date
            FROM board_projects bp
            LEFT JOIN project_mapping pm ON pm.board_project_id = bp.id
            WHERE pm.board_project_id IS NULL
              AND bp.order_status IN ({won_in})
              AND COALESCE(bp.is_excluded, 0) = 0
              {date_clause}
            ORDER BY bp.updated_at DESC
            """,
            date_params,
        ).fetchall()
        unmatched = []
        for r in raw_unmatched:
            name_l = (r["name"] or "").lower()
            client_l = (r["client_name"] or "").lower()
            if any(g in name_l or g in client_l for g in group_names):
                continue  # 自動マッチ済みなのでスキップ
            unmatched.append(r)
            if len(unmatched) >= 50:
                break

        # 請求済み / 未請求 金額（受注済み案件のみ）
        today = datetime.now(timezone.utc).date().isoformat()
        won_projects = conn.execute(
            f"SELECT total_amount, invoice_dates FROM board_projects WHERE order_status IN ({won_in}) {date_clause}",
            date_params,
        ).fetchall()
        invoiced_amount = un_invoiced_amount = 0
        for wp in won_projects:
            amt = wp["total_amount"] or 0
            dates = json.loads(wp["invoice_dates"] or "[]")
            if dates and any(d <= today for d in dates):
                invoiced_amount += amt
            else:
                un_invoiced_amount += amt

        # 利用可能な年度一覧（DBにある estimate_date から算出）
        fy_rows = conn.execute(
            "SELECT DISTINCT SUBSTR(estimate_date, 1, 7) AS ym FROM board_projects WHERE estimate_date IS NOT NULL AND estimate_date != '' ORDER BY ym"
        ).fetchall()
        available_years: set[int] = set()
        for row in fy_rows:
            ym = row["ym"]  # "2026-05" 形式
            y, m = int(ym[:4]), int(ym[5:7])
            fy = y if m >= 3 else y - 1
            available_years.add(fy)

        return {
            "fiscal_year": fiscal_year,
            "available_fiscal_years": sorted(available_years),
            "win_rate": round(win_rate, 1) if win_rate is not None else None,
            "won": won,
            "lost": lost,
            "active": active,
            "overdue_tasks_total": overdue,
            "unmatched_won": [dict(r) for r in unmatched],
            "invoiced_amount": invoiced_amount,
            "un_invoiced_amount": un_invoiced_amount,
        }
    finally:
        conn.close()


def get_invoice_breakdown(fiscal_year: int | None = None, kind: str = "invoiced") -> list[dict]:
    """請求済み or 未請求 の受注案件詳細リストを返す。

    kind: 'invoiced' = いずれかの請求日が過去 / 'un_invoiced' = それ以外。
    """
    if kind not in ("invoiced", "un_invoiced"):
        raise ValueError("kind must be 'invoiced' or 'un_invoiced'")

    today = datetime.now(timezone.utc).date().isoformat()
    won_in = ",".join(f"'{w}'" for w in WON_STATUSES)

    if fiscal_year:
        period_start, period_end = _fiscal_year_range(fiscal_year)
        date_clause = "AND estimate_date >= ? AND estimate_date <= ? AND estimate_date IS NOT NULL"
        date_params: tuple = (period_start, period_end)
    else:
        date_clause = ""
        date_params = ()

    conn = get_conn()
    try:
        rows = conn.execute(
            f"""
            SELECT id, name, client_name, total_amount, invoice_dates, estimate_date
            FROM board_projects
            WHERE order_status IN ({won_in}) {date_clause}
            ORDER BY estimate_date DESC
            """,
            date_params,
        ).fetchall()

        result = []
        for r in rows:
            dates = json.loads(r["invoice_dates"] or "[]")
            has_past = bool(dates and any(d <= today for d in dates))
            want = (kind == "invoiced" and has_past) or (kind == "un_invoiced" and not has_past)
            if not want:
                continue
            result.append({
                "id": r["id"],
                "name": r["name"],
                "client_name": r["client_name"],
                "total_amount": r["total_amount"],
                "invoice_dates": dates,
                "estimate_date": r["estimate_date"],
            })
        return result
    finally:
        conn.close()


def get_won_progress() -> list[dict]:
    """受注済み案件の進捗リスト（Repsona 親タスクグループ × board 案件の突合）。

    Repsona の親タスク名（= 案件ヘッダー）と board のプロジェクト名・クライアント名を
    部分文字列マッチで紐付ける。金額 × 遅れ度の高い順にソートして返す。
    """
    conn = get_conn()
    try:
        groups = conn.execute(
            "SELECT group_name, task_total, task_done, task_overdue FROM repsona_task_groups ORDER BY group_name"
        ).fetchall()

        won_in = ",".join(f"'{w}'" for w in WON_STATUSES)
        board_won = conn.execute(
            f"SELECT id, name, client_name, total_amount, estimate_date FROM board_projects WHERE order_status IN ({won_in})"
        ).fetchall()

        # 手動マッピング: group_name -> {board_project_ids}
        # 既存スキーマの repsona_project_id を group_name 格納用として再利用
        manual_map: dict[str, set[int]] = {}
        for m in conn.execute(
            "SELECT board_project_id, repsona_project_id FROM project_mapping WHERE match_type = 'manual'"
        ).fetchall():
            manual_map.setdefault(m["repsona_project_id"], set()).add(m["board_project_id"])

        result = []
        for g in groups:
            gname = g["group_name"]
            gname_lower = gname.lower()
            manual_ids = manual_map.get(gname, set())

            # 案件名/クライアント名に親タスク名が含まれる、または手動紐付け済みの board 案件
            matched = [
                p for p in board_won
                if p["id"] in manual_ids
                or gname_lower in (p["name"] or "").lower()
                or gname_lower in (p["client_name"] or "").lower()
            ]
            total_amount = sum(p["total_amount"] or 0 for p in matched)

            t_total = g["task_total"]
            t_done  = g["task_done"]
            t_over  = g["task_overdue"]

            actual_pct = round(t_done / t_total * 100) if t_total else 0
            ideal_pct  = round((t_done + t_over) / t_total * 100) if t_total else 0

            budget_days = round(total_amount / AVG_DAILY_RATE, 1) if total_amount else None

            result.append({
                "group_name":    gname,
                "total_amount":  total_amount,
                "budget_days":   budget_days,
                "task_total":    t_total,
                "task_done":     t_done,
                "task_overdue":  t_over,
                "actual_pct":   actual_pct,
                "ideal_pct":    ideal_pct,
                "board_projects": [
                    {"id": p["id"], "name": p["name"], "client_name": p["client_name"]}
                    for p in matched
                ],
            })

        # 遅れ件数 × 金額の大きい順（最も注意が必要な案件が先頭）
        result.sort(key=lambda x: x["task_overdue"] * (x["total_amount"] or 1), reverse=True)
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    print(json.dumps(get_kpis(), ensure_ascii=False, indent=2, default=str))
