"""SQLite スキーマ。冪等に何度実行してもOK。"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS board_projects (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    client_name     TEXT,
    order_status    TEXT,           -- '受注', '失注', '見積中' など（実装は文字列でゆるく）
    total_amount    INTEGER,        -- 税込合計
    updated_at      TEXT,           -- board側のupdated_at
    last_seen_at    TEXT NOT NULL,  -- 最後にAPIで取得した時刻
    prev_status     TEXT            -- 前回のorder_status（差分検知用）
);

CREATE TABLE IF NOT EXISTS repsona_projects (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    task_total      INTEGER DEFAULT 0,
    task_done       INTEGER DEFAULT 0,
    task_overdue    INTEGER DEFAULT 0,
    updated_at      TEXT,
    last_seen_at    TEXT NOT NULL
);

-- 手動・自動どちらでも紐付けるマッピング表
CREATE TABLE IF NOT EXISTS project_mapping (
    board_project_id     INTEGER NOT NULL,
    repsona_project_id   TEXT NOT NULL,
    match_type           TEXT NOT NULL,  -- 'auto_prefix' | 'manual' | 'fuzzy'
    confidence           REAL DEFAULT 1.0,
    created_at           TEXT NOT NULL,
    PRIMARY KEY (board_project_id, repsona_project_id)
);

-- 同じイベントを二回通知しないためのガード
CREATE TABLE IF NOT EXISTS notifications_sent (
    board_project_id     INTEGER NOT NULL,
    event_type           TEXT NOT NULL,    -- 'order_won' など
    sent_at              TEXT NOT NULL,
    PRIMARY KEY (board_project_id, event_type)
);

-- Repsona の親タスク（＝案件ヘッダー）単位の進捗集計
CREATE TABLE IF NOT EXISTS repsona_task_groups (
    group_name      TEXT PRIMARY KEY,   -- 親タスク名（例: "三幸学園"）
    task_total      INTEGER DEFAULT 0,
    task_done       INTEGER DEFAULT 0,
    task_overdue    INTEGER DEFAULT 0,
    last_seen_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_board_status ON board_projects(order_status);
CREATE INDEX IF NOT EXISTS idx_board_updated ON board_projects(updated_at);
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        # 既存DBへのカラム追加（冪等）
        for stmt in [
            "ALTER TABLE board_projects ADD COLUMN estimate_date TEXT",
            "ALTER TABLE board_projects ADD COLUMN invoice_dates TEXT",
            "ALTER TABLE board_projects ADD COLUMN is_excluded INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # already exists
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    init_db()
    print(f"Initialized DB at {DB_PATH}")
