import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sender_summaries (
    sender_email    TEXT PRIMARY KEY,
    display_name    TEXT,
    summary         TEXT,
    message_count   INTEGER DEFAULT 0,
    last_updated    INTEGER,
    matched_rule    TEXT,
    pending_action  TEXT DEFAULT 'none'
);

CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   TEXT PRIMARY KEY,
    thread_id    TEXT,
    processed_at INTEGER
);

CREATE TABLE IF NOT EXISTS run_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at           INTEGER,
    messages_seen    INTEGER,
    messages_matched INTEGER,
    llm_calls        INTEGER,
    errors           TEXT
);
"""


class Storage:
    def __init__(self, db_path: str = "./agent.db"):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # --- Sender summaries ---

    def get_sender_summary(self, sender_email: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM sender_summaries WHERE sender_email = ?", (sender_email,)
            ).fetchone()
            return dict(row) if row else None

    def upsert_sender_summary(
        self,
        sender_email: str,
        display_name: str,
        summary: str,
        matched_rule: str,
        pending_action: str = "none",
        message_count_delta: int = 1,
    ):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO sender_summaries
                    (sender_email, display_name, summary, message_count, last_updated, matched_rule, pending_action)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sender_email) DO UPDATE SET
                    display_name   = excluded.display_name,
                    summary        = excluded.summary,
                    message_count  = message_count + ?,
                    last_updated   = excluded.last_updated,
                    matched_rule   = excluded.matched_rule,
                    pending_action = excluded.pending_action
                """,
                (sender_email, display_name, summary, message_count_delta, now, matched_rule, pending_action,
                 message_count_delta),
            )

    def get_all_sender_summaries(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM sender_summaries ORDER BY last_updated DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Processed messages ---

    def is_processed(self, message_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,)
            ).fetchone()
            return row is not None

    def clear_processed_since(self, since_timestamp: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM processed_messages WHERE processed_at >= ?",
                (since_timestamp,),
            )

    def mark_processed(self, message_id: str, thread_id: str):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_messages (message_id, thread_id, processed_at) VALUES (?, ?, ?)",
                (message_id, thread_id, now),
            )

    # --- Run log ---

    def log_run(
        self,
        run_at: int,
        messages_seen: int,
        messages_matched: int,
        llm_calls: int,
        errors: str = "",
    ):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO run_log (run_at, messages_seen, messages_matched, llm_calls, errors) VALUES (?, ?, ?, ?, ?)",
                (run_at, messages_seen, messages_matched, llm_calls, errors),
            )

    def get_last_run_timestamp(self) -> int:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(run_at) as last_run FROM run_log"
            ).fetchone()
            if row and row["last_run"]:
                return row["last_run"]
            return int(time.time()) - 86400


if __name__ == "__main__":
    import os

    db_path = "./test_agent.db"
    storage = Storage(db_path)
    print("DB initialised at:", db_path)
    with storage._conn() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for t in tables:
            print(" ", t["name"])
    os.remove(db_path)
    print("Test DB removed.")
