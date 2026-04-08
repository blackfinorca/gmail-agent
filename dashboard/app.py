import os
import re
import sys
import time

from flask import Flask, abort, render_template

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from storage import Storage

app = Flask(__name__)

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "agent.db"))
storage = Storage(DB_PATH)


def relative_time(ts: int) -> str:
    if not ts:
        return "never"
    diff = int(time.time()) - ts
    if diff < 60:
        return f"{diff}s ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    return f"{diff // 86400}d ago"


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


@app.route("/")
def index():
    senders = storage.get_all_sender_summaries()
    last_run = storage.get_last_run_timestamp()
    for s in senders:
        s["relative_time"] = relative_time(s.get("last_updated", 0))
        s["summary_snippet"] = strip_html(s.get("summary", ""))[:120]
    return render_template(
        "index.html",
        senders=senders,
        total=len(senders),
        last_run=relative_time(last_run),
    )


@app.route("/sender/<path:sender_email>")
def sender_detail(sender_email):
    sender = storage.get_sender_summary(sender_email)
    if not sender:
        abort(404)
    sender["relative_time"] = relative_time(sender.get("last_updated", 0))
    return render_template("sender.html", sender=sender)


if __name__ == "__main__":
    app.run(host="localhost", port=5050, debug=False)
