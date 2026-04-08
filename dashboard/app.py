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


@app.route("/")
def index():
    threads = storage.get_all_threads()
    last_run = storage.get_last_run_timestamp()
    for t in threads:
        t["relative_time"] = relative_time(t.get("last_updated", 0))
        raw = re.sub(r"<[^>]+>", " ", t.get("summary") or "")
        t["summary_snippet"] = re.sub(r"\s+", " ", raw).strip()[:120]
    return render_template(
        "index.html",
        threads=threads,
        total=len(threads),
        last_run=relative_time(last_run),
    )


@app.route("/thread/<thread_id>")
def thread_detail(thread_id):
    thread = storage.get_summary(thread_id)
    if not thread:
        abort(404)
    thread["relative_time"] = relative_time(thread.get("last_updated", 0))
    return render_template("thread.html", thread=thread)


if __name__ == "__main__":
    app.run(host="localhost", port=5050, debug=False)
