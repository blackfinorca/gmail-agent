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
    threads = storage.get_all_thread_summaries()
    last_run = storage.get_last_run_timestamp()
    for t in threads:
        t["relative_time"] = relative_time(t.get("last_updated", 0))
        t["summary_snippet"] = strip_html(t.get("summary", ""))[:120]
    return render_template(
        "index.html",
        threads=threads,
        total=len(threads),
        last_run=relative_time(last_run),
    )


@app.route("/thread/<path:thread_name>")
def thread_detail(thread_name):
    thread = storage.get_thread_summary(thread_name)
    if not thread:
        abort(404)
    thread["relative_time"] = relative_time(thread.get("last_updated", 0))
    return render_template("thread.html", thread=thread)


@app.route("/invoices")
def invoices():
    rows = storage.get_all_invoices()
    for r in rows:
        r["sent_display"] = relative_time(r.get("sent_at", 0))
    return render_template("invoices.html", invoices=rows, total=len(rows))


if __name__ == "__main__":
    app.run(host="localhost", port=5050, debug=False)
