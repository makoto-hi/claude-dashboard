"""board案件とRepsonaプロジェクトの突合。

3段階：
  1. Repsona名に '案件#<数字>' があれば確実マッチ
  2. 案件名とプロジェクト名の類似度が高ければ候補（fuzzy）
  3. それでもマッチしなければ未マッチ

突合結果は project_mapping に書き込む。手動マッピング（match_type='manual'）
は触らない（人間が決めたものを上書きしない）。
"""
from __future__ import annotations
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from db import get_conn

PREFIX_RE = re.compile(r"案件\s*#\s*(\d+)")
FUZZY_THRESHOLD = 0.7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rebuild_auto_mappings() -> dict:
    """auto系のマッピングだけ作り直す。manual はそのまま残す。"""
    conn = get_conn()
    try:
        # manual以外を一旦削除
        conn.execute("DELETE FROM project_mapping WHERE match_type != 'manual'")

        board_rows = conn.execute(
            "SELECT id, name FROM board_projects"
        ).fetchall()
        repsona_rows = conn.execute(
            "SELECT id, name FROM repsona_projects"
        ).fetchall()
        board_by_id = {b["id"]: b for b in board_rows}

        prefix_count = 0
        fuzzy_count = 0
        unmatched_repsona = []

        # 1. prefix マッチ
        used_repsona = set()
        for rp in repsona_rows:
            m = PREFIX_RE.search(rp["name"] or "")
            if not m:
                unmatched_repsona.append(rp)
                continue
            bid = int(m.group(1))
            if bid in board_by_id:
                conn.execute(
                    """INSERT OR REPLACE INTO project_mapping
                       (board_project_id, repsona_project_id, match_type, confidence, created_at)
                       VALUES (?, ?, 'auto_prefix', 1.0, ?)""",
                    (bid, rp["id"], _now()),
                )
                used_repsona.add(rp["id"])
                prefix_count += 1

        # 2. fuzzy マッチ（残り）
        mapped_board_ids = {
            r["board_project_id"]
            for r in conn.execute("SELECT board_project_id FROM project_mapping").fetchall()
        }
        for rp in unmatched_repsona:
            if rp["id"] in used_repsona:
                continue
            best_id, best_score = None, 0.0
            for b in board_rows:
                if b["id"] in mapped_board_ids:
                    continue
                score = SequenceMatcher(None, rp["name"] or "", b["name"] or "").ratio()
                if score > best_score:
                    best_id, best_score = b["id"], score
            if best_id and best_score >= FUZZY_THRESHOLD:
                conn.execute(
                    """INSERT OR REPLACE INTO project_mapping
                       (board_project_id, repsona_project_id, match_type, confidence, created_at)
                       VALUES (?, ?, 'fuzzy', ?, ?)""",
                    (best_id, rp["id"], best_score, _now()),
                )
                mapped_board_ids.add(best_id)
                fuzzy_count += 1

        conn.commit()
        return {"prefix": prefix_count, "fuzzy": fuzzy_count}
    finally:
        conn.close()


def add_manual_mapping(board_id: int, repsona_id: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO project_mapping
               (board_project_id, repsona_project_id, match_type, confidence, created_at)
               VALUES (?, ?, 'manual', 1.0, ?)""",
            (board_id, repsona_id, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def promote_to_solo(board_id: int) -> None:
    """board案件を単独グループとして受注案件の進捗に登録する。
    Repsonaのいずれのグループにも属さず、独立した行として表示される。"""
    conn = get_conn()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO project_mapping
               (board_project_id, repsona_project_id, match_type, confidence, created_at)
               VALUES (?, ?, 'manual_solo', 1.0, ?)""",
            (board_id, f"__solo:{board_id}", _now()),
        )
        conn.commit()
    finally:
        conn.close()
