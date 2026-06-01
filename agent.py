import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time
from typing import Optional

import schedule
from dotenv import load_dotenv

from attachments import pdf_to_text
from config import load_config
from filter_engine import FilterEngine
from gmail_client import GmailClient
from storage import Storage
from summariser import Summariser

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

load_dotenv()

PID_FILE = os.getenv("PID_FILE", "./agent.pid")


def setup_logging(log_file: str):
    handlers = [
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=3
        ),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


logger = logging.getLogger(__name__)


class Agent:
    def __init__(self):
        self.config = load_config()
        self.db_path = os.getenv("DB_PATH", "./agent.db")
        self.credentials_dir = os.getenv("CREDENTIALS_DIR", "./credentials")
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")

        self.storage = Storage(self.db_path)
        self.gmail = GmailClient(credentials_dir=self.credentials_dir)
        self.gmail.authenticate()
        self.filter = FilterEngine(self.config)
        self.summariser = Summariser(
            api_key=self.api_key, max_tokens=self.config.max_summary_tokens
        )
        self._pending_reload = False

    def _reload_config(self):
        self.config = load_config()
        self.filter = FilterEngine(self.config)
        logger.info(
            "Rules reloaded — %d threads, %d invoice groups",
            len(self.config.thread_list),
            len(self.config.invoice_groups),
        )
        print(f"  Rules reloaded: thread_list={self.config.thread_list}  invoice_groups={self.config.invoice_groups}")

    def _handle_sigusr1(self, signum, frame):
        self._pending_reload = True

    @staticmethod
    def _extract_email(sender_str: str) -> str:
        """Extract bare email address from 'Name <email>' or return as-is."""
        import re
        m = re.search(r"<([^>]+)>", sender_str)
        return m.group(1).lower().strip() if m else sender_str.lower().strip()

    @staticmethod
    def _invoice_key(invoice_number: str, sender_email: str, message_id: str) -> str:
        """Dedupe key: invoice_number+sender, else fall back to message_id."""
        num = (invoice_number or "").strip()
        if num:
            return f"{num}|{sender_email}"
        return message_id

    @staticmethod
    def _extract_attachment_text(gmail, msg: dict) -> str:
        """Download every PDF attachment (<=10MB) and return its extracted text."""
        parts = []
        for att in msg.get("attachments", []):
            if att.get("mime_type") != "application/pdf":
                continue
            if att.get("size", 0) and att["size"] > MAX_ATTACHMENT_BYTES:
                logger.info("Skipping large attachment %s (%d bytes)", att["filename"], att["size"])
                continue
            try:
                data = gmail.download_attachment(msg["id"], att["attachment_id"])
                text = pdf_to_text(data)
                if text:
                    parts.append(f"--- {att['filename']} ---\n{text}")
                else:
                    logger.info("No text extracted from attachment %s", att["filename"])
            except Exception as e:
                logger.error("Failed to read attachment %s: %s", att.get("filename"), e)
        return "\n\n".join(parts)

    @staticmethod
    def _parse_date_to_ts(date_str: str) -> int:
        """Parse an RFC-2822 email Date header to a unix ts; fall back to now."""
        from email.utils import parsedate_to_datetime
        try:
            return int(parsedate_to_datetime(date_str).timestamp())
        except (TypeError, ValueError):
            return int(time.time())

    def run_once(self, since_override: Optional[int] = None):
        run_at = int(time.time())
        messages_seen = 0
        messages_matched = 0
        llm_calls = 0
        errors = []

        # Default: scan the whole mailbox (since=0). --since only narrows it.
        # Already-processed messages are skipped before download, so repeat
        # polls stay cheap even though the listing covers all dates.
        since = since_override if since_override is not None else 0
        if since_override is not None:
            self.storage.clear_processed_since(since_override)
            logger.info("Cleared processed-message cache from %d onwards for rescan", since_override)
        logger.info("Polling for messages since timestamp %d", since)

        try:
            messages = self.gmail.fetch_new_messages(
                since, skip_ids=self.storage.get_processed_ids()
            )
        except Exception as e:
            logger.error("Failed to fetch messages: %s", e)
            errors.append(str(e))
            self.storage.log_run(run_at, 0, 0, 0, "; ".join(errors))
            return

        messages_seen = len(messages)
        logger.info("Fetched %d message(s)", messages_seen)

        # Route unprocessed messages into the two pipelines
        thread_batches: dict[str, list] = {}
        invoice_msgs: list = []
        for msg in messages:
            if self.storage.is_processed(msg["id"]):
                continue
            thread_name = self.filter.thread_for(msg)
            if thread_name is not None:
                thread_batches.setdefault(thread_name, []).append(msg)
            if self.filter.invoice_group_for(msg) is not None:
                invoice_msgs.append(msg)

        messages_matched = sum(len(v) for v in thread_batches.values()) + len(invoice_msgs)

        # --- Thread pipeline: one rolling summary per named thread ---
        for thread_name, batch in thread_batches.items():
            members = ", ".join(self.config.thread_list.get(thread_name, []))
            logger.info("Processing %d message(s) for thread %r", len(batch), thread_name)

            try:
                existing = self.storage.get_thread_summary(thread_name)
                existing_summary = existing["summary"] if existing else ""

                new_summary, pending_action = self.summariser.update_sender_summary(
                    existing_summary, batch
                )
                llm_calls += 1

                for msg in batch:
                    self.storage.mark_processed(msg["id"], msg["thread_id"])

                self.storage.upsert_thread_summary(
                    thread_name=thread_name,
                    members=members,
                    summary=new_summary,
                    pending_action=pending_action,
                    message_count_delta=len(batch),
                )
                logger.info("Thread summary updated for %r (%d new messages)", thread_name, len(batch))

            except Exception as e:
                logger.error("Error processing thread %r: %s", thread_name, e)
                errors.append(f"thread:{thread_name} — {e}")

        # --- Invoice pipeline: structured extraction per message ---
        for msg in invoice_msgs:
            sender_email = self._extract_email(msg["sender"])
            group = self.filter.invoice_group_for(msg) or ""
            try:
                msg = {**msg, "attachments_text": self._extract_attachment_text(self.gmail, msg)}
                data = self.summariser.extract_invoice(msg)
                llm_calls += 1
                self.storage.mark_processed(msg["id"], msg["thread_id"])

                if not data.get("is_invoice"):
                    logger.info("Message %s from %s is not an invoice — skipped", msg["id"], sender_email)
                    continue

                key = self._invoice_key(data["invoice_number"], sender_email, msg["id"])
                self.storage.upsert_invoice(
                    invoice_key=key,
                    message_id=msg["id"],
                    sender_email=sender_email,
                    invoice_group=group,
                    billed_to=data["billed_to"],
                    invoice_name=data["invoice_name"],
                    company=data["company"],
                    invoice_number=data["invoice_number"],
                    amount=data["amount"],
                    sent_at=self._parse_date_to_ts(msg.get("date", "")),
                    payable_at=data["payable_at"],
                    link=data["link"],
                )
                logger.info("Invoice stored: %s (%s) from %s", key, group, sender_email)

            except Exception as e:
                logger.error("Error processing invoice from %s: %s", sender_email, e)
                errors.append(f"invoice:{sender_email} — {e}")

        self.storage.log_run(
            run_at=run_at,
            messages_seen=messages_seen,
            messages_matched=messages_matched,
            llm_calls=llm_calls,
            errors="; ".join(errors),
        )
        logger.info(
            "Run complete: seen=%d matched=%d llm_calls=%d errors=%d",
            messages_seen,
            messages_matched,
            llm_calls,
            len(errors),
        )

    def _start_dashboard(self):
        sys.path.insert(0, os.path.dirname(__file__))
        from dashboard.app import app as flask_app

        t = threading.Thread(
            target=lambda: flask_app.run(
                host="localhost", port=5050, debug=False, use_reloader=False
            ),
            daemon=True,
            name="dashboard",
        )
        t.start()
        logger.info("Dashboard started at http://localhost:5050")
        print("  Dashboard      : http://localhost:5050")

    def run_forever(self, with_dashboard: bool = False, since_override: Optional[int] = None):
        interval = self.config.poll_interval_seconds
        print("=" * 60)
        print("  Gmail Intelligence Agent")
        print("=" * 60)
        print(f"  Poll interval  : {interval}s")
        print(f"  Thread senders : {self.config.thread_list}")
        print(f"  Invoice groups : {self.config.invoice_groups}")
        print(f"  DB path        : {self.db_path}")
        print(f"  PID file       : {PID_FILE}  (PID {os.getpid()})")
        print(f"  Reload rules   : python agent.py --reload-rules")

        if with_dashboard:
            self._start_dashboard()

        print("=" * 60)

        signal.signal(signal.SIGUSR1, self._handle_sigusr1)

        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

        self.run_once(since_override=since_override)

        schedule.every(interval).seconds.do(self.run_once)

        try:
            while True:
                if self._pending_reload:
                    self._reload_config()
                    self._pending_reload = False
                    schedule.clear()
                    schedule.every(self.config.poll_interval_seconds).seconds.do(self.run_once)
                    self.run_once()
                schedule.run_pending()
                time.sleep(5)
        finally:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)


def parse_since(value: str) -> int:
    """Parse a --since value like '7d', '12h', '30m' into a unix timestamp."""
    units = {"m": 60, "h": 3600, "d": 86400}
    value = value.strip().lower()
    if value[-1] not in units:
        raise argparse.ArgumentTypeError(f"Invalid --since value '{value}'. Use e.g. 7d, 12h, 30m.")
    try:
        amount = int(value[:-1])
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid --since value '{value}'. Use e.g. 7d, 12h, 30m.")
    return int(time.time()) - amount * units[value[-1]]


def send_reload_signal():
    if not os.path.exists(PID_FILE):
        print(f"ERROR: PID file not found at {PID_FILE}. Is the agent running?")
        sys.exit(1)
    with open(PID_FILE) as f:
        pid = int(f.read().strip())
    os.kill(pid, signal.SIGUSR1)
    print(f"Sent reload signal to agent (PID {pid}). Rules will refresh on next check.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gmail Intelligence Agent")
    parser.add_argument(
        "--once", action="store_true", help="Run a single poll cycle then exit"
    )
    parser.add_argument(
        "--with-dashboard",
        action="store_true",
        help="Also start the Flask dashboard on localhost:5050",
    )
    parser.add_argument(
        "--reload-rules",
        action="store_true",
        help="Signal the running agent to reload rules.json immediately",
    )
    parser.add_argument(
        "--since",
        metavar="DURATION",
        help="Override lookback window, e.g. 7d, 12h, 30m. Clears processed-message cache for that window.",
    )
    args = parser.parse_args()

    if args.reload_rules:
        send_reload_signal()
        sys.exit(0)

    since_override = None
    if args.since:
        since_override = parse_since(args.since)
        print(f"  Lookback override: {args.since} (since {time.strftime('%Y-%m-%d %H:%M', time.localtime(since_override))})")

    log_file = os.getenv("LOG_FILE", "./agent.log")
    setup_logging(log_file)

    agent = Agent()

    if args.once:
        agent.run_once(since_override=since_override)
    else:
        agent.run_forever(with_dashboard=args.with_dashboard, since_override=since_override)
