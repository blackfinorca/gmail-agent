import argparse
import logging
import logging.handlers
import os
import signal
import sys
import threading
import time

import schedule
from dotenv import load_dotenv

from config import load_config
from filter_engine import FilterEngine
from gmail_client import GmailClient
from storage import Storage
from summariser import Summariser

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
            "Rules reloaded — %d senders, %d keywords",
            len(self.config.sender_whitelist),
            len(self.config.keywords),
        )
        print(f"  Rules reloaded: senders={self.config.sender_whitelist}  keywords={self.config.keywords}")

    def _handle_sigusr1(self, signum, frame):
        self._pending_reload = True

    def run_once(self, since_override: int | None = None):
        run_at = int(time.time())
        messages_seen = 0
        messages_matched = 0
        llm_calls = 0
        errors = []

        since = since_override if since_override is not None else self.storage.get_last_run_timestamp()
        if since_override is not None:
            self.storage.clear_processed_since(since_override)
            logger.info("Cleared processed-message cache from %d onwards for rescan", since_override)
        logger.info("Polling for messages since timestamp %d", since)

        try:
            messages = self.gmail.fetch_new_messages(since)
        except Exception as e:
            logger.error("Failed to fetch messages: %s", e)
            errors.append(str(e))
            self.storage.log_run(run_at, 0, 0, 0, "; ".join(errors))
            return

        messages_seen = len(messages)
        logger.info("Fetched %d message(s)", messages_seen)

        for msg in messages:
            msg_id = msg["id"]
            thread_id = msg["thread_id"]

            if self.storage.is_processed(msg_id):
                continue

            if not self.filter.matches(msg):
                continue

            messages_matched += 1
            rule = self.filter.classify(msg)
            logger.info("Matched message %s (rule: %s)", msg_id, rule)

            try:
                thread_messages = self.gmail.fetch_thread_messages(thread_id)
                if not thread_messages:
                    thread_messages = [msg]  # fallback to just the triggering message

                new_summary, pending_action = self.summariser.summarise_thread(thread_messages)
                llm_calls += 1

                # Mark all messages in the thread as processed
                for tm in thread_messages:
                    self.storage.mark_processed(tm["id"], thread_id)

                self.storage.upsert_summary(
                    thread_id=thread_id,
                    sender=msg["sender"],
                    subject=msg["subject"],
                    summary=new_summary,
                    matched_rule=rule,
                    pending_action=pending_action,
                )
                logger.info("Summary updated for thread %s (%d messages)", thread_id, len(thread_messages))

            except Exception as e:
                logger.error("Error processing message %s: %s", msg_id, e)
                errors.append(f"msg:{msg_id} — {e}")

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

    def run_forever(self, with_dashboard: bool = False, since_override: int | None = None):
        interval = self.config.poll_interval_seconds
        print("=" * 60)
        print("  Gmail Intelligence Agent")
        print("=" * 60)
        print(f"  Poll interval  : {interval}s")
        print(f"  Sender rules   : {self.config.sender_whitelist}")
        print(f"  Keywords       : {self.config.keywords}")
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
