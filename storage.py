import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS thread_summaries (
    thread_name     TEXT PRIMARY KEY,
    members         TEXT,
    summary         TEXT,
    message_count   INTEGER DEFAULT 0,
    last_updated    INTEGER,
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

CREATE TABLE IF NOT EXISTS invoices (
    invoice_key     TEXT PRIMARY KEY,
    message_id      TEXT,
    sender_email    TEXT,
    invoice_group   TEXT,
    billed_to       TEXT,
    invoice_name    TEXT,
    company         TEXT,
    invoice_number  TEXT,
    amount          TEXT,
    sent_at         INTEGER,
    payable_at      TEXT,
    link            TEXT,
    created_at      INTEGER
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

    # --- Thread summaries ---

    def get_thread_summary(self, thread_name: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM thread_summaries WHERE thread_name = ?", (thread_name,)
            ).fetchone()
            return dict(row) if row else None

    def upsert_thread_summary(
        self,
        thread_name: str,
        members: str,
        summary: str,
        pending_action: str = "none",
        message_count_delta: int = 1,
    ):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO thread_summaries
                    (thread_name, members, summary, message_count, last_updated, pending_action)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_name) DO UPDATE SET
                    members        = excluded.members,
                    summary        = excluded.summary,
                    message_count  = message_count + ?,
                    last_updated   = excluded.last_updated,
                    pending_action = excluded.pending_action
                """,
                (thread_name, members, summary, message_count_delta, now, pending_action,
                 message_count_delta),
            )

    def get_all_thread_summaries(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM thread_summaries ORDER BY last_updated DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Invoices ---

    def upsert_invoice(
        self,
        invoice_key: str,
        message_id: str,
        sender_email: str,
        invoice_group: str,
        billed_to: str,
        invoice_name: str,
        company: str,
        invoice_number: str,
        amount: str,
        sent_at: int,
        payable_at: str,
        link: str,
    ):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoices
                    (invoice_key, message_id, sender_email, invoice_group, billed_to,
                     invoice_name, company, invoice_number, amount, sent_at, payable_at,
                     link, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(invoice_key) DO UPDATE SET
                    message_id     = excluded.message_id,
                    sender_email   = excluded.sender_email,
                    invoice_group  = excluded.invoice_group,
                    billed_to      = excluded.billed_to,
                    invoice_name   = excluded.invoice_name,
                    company        = excluded.company,
                    invoice_number = excluded.invoice_number,
                    amount         = excluded.amount,
                    sent_at        = excluded.sent_at,
                    payable_at     = excluded.payable_at,
                    link           = excluded.link
                """,
                (invoice_key, message_id, sender_email, invoice_group, billed_to,
                 invoice_name, company, invoice_number, amount, sent_at, payable_at,
                 link, now),
            )

    def get_all_invoices_grouped(self) -> dict[str, list[dict]]:
        """All invoices keyed by invoice_group (preserves sent_at DESC order)."""
        grouped: dict[str, list[dict]] = {}
        for row in self.get_all_invoices():
            grouped.setdefault(row.get("invoice_group") or "Ungrouped", []).append(row)
        return grouped

    def get_all_invoices(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM invoices ORDER BY sent_at DESC"
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
