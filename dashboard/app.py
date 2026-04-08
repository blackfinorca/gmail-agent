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

    grouped = {}  # sender -> {sender, matched_rule, last_updated, threads[]}
    for t in threads:
        t["relative_time"] = relative_time(t.get("last_updated", 0))
        raw = re.sub(r"<[^>]+>", " ", t.get("summary") or "")
        t["summary_snippet"] = re.sub(r"\s+", " ", raw).strip()[:120]

        sender = t.get("sender") or "Unknown"
        if sender not in grouped:
            grouped[sender] = {
                "sender": sender,
                "matched_rule": t.get("matched_rule", ""),
                "last_updated": t.get("last_updated", 0),
                "threads": [],
            }
        else:
            # Keep the group's last_updated as the most recent thread
            if (t.get("last_updated") or 0) > grouped[sender]["last_updated"]:
                grouped[sender]["last_updated"] = t["last_updated"]

        grouped[sender]["threads"].append(t)

    # Sort groups by most recently updated, threads within each group likewise
    sender_groups = sorted(grouped.values(), key=lambda g: g["last_updated"], reverse=True)
    for g in sender_groups:
        g["last_updated_rel"] = relative_time(g["last_updated"])

    return render_template(
        "index.html",
        sender_groups=sender_groups,
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
