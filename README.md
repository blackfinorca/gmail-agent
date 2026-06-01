# Gmail Intelligence Agent

A Python agent that polls a Gmail account and runs two pipelines: an **Emails**
pipeline that maintains an always-current **one-pager briefing per named
thread** (matched by subject keywords), and an **Invoices** pipeline that
extracts structured invoice fields from a separate sender list — both rendered
in a small local Flask dashboard.

Summaries are written by OpenAI (`gpt-4o-mini`, override via `OPENAI_MODEL`) in a fixed
briefing-note format: TL;DR, key decisions, timeline, open items, next action.
Each thread also has a `pending_action` flag (`you` / `them` / `none`) so you
can see at a glance who owes whom a reply.

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Invoice PDFs are read **natively by the multimodal model** — no OCR or system
binaries to install.

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set OPENAI_API_KEY_EMAILS (and OPENAI_API_KEY_PDF)
```

`.env` keys:

| Key                       | Default            | Notes |
|---------------------------|--------------------|-------|
| `OPENAI_API_KEY_EMAILS`   | _(required)_       | OpenAI key for email summaries |
| `OPENAI_API_KEY_PDF`      | _(falls back to emails key)_ | OpenAI key for invoice PDF extraction |
| `OPENAI_MODEL`            | `gpt-4o-mini`      | Text model for summaries |
| `OPENAI_PDF_MODEL`        | `gpt-4o-mini`      | Multimodal model for invoice PDFs |
| `POLL_INTERVAL_SECONDS`   | `300`              | How often the agent polls Gmail |
| `MAX_SUMMARY_TOKENS`      | `400`              | Word-count hint passed to the model |
| `DB_PATH`                 | `./agent.db`       | SQLite file |
| `CREDENTIALS_DIR`         | `./credentials`    | OAuth client + token live here |
| `LOG_FILE`                | `./agent.log`      | Rotating log file |
| `PID_FILE`                | `./agent.pid`      | Used by `--reload-rules` |

### 3. Enable the Gmail API

1. Open [console.cloud.google.com](https://console.cloud.google.com).
2. Create or pick a project.
3. **APIs & Services → Enable APIs** → enable **Gmail API**.
4. **Credentials → Create Credentials → OAuth client ID** → application type
   **Desktop app**.
5. Download the JSON and save it as `credentials/credentials.json`.
6. Under **OAuth consent screen**, add your own Gmail address as a **test user**.

---

## First run (OAuth)

```bash
python agent.py --once
```

This opens a browser window for Google consent. After approval,
`credentials/token.json` is saved and reused (with auto-refresh) on every
subsequent run.

---

## Running the agent

```bash
# Continuous: polls every POLL_INTERVAL_SECONDS
python agent.py

# Continuous + dashboard on http://localhost:5050
python agent.py --with-dashboard

# One poll, then exit (handy for cron or testing).
# By default this scans the WHOLE mailbox; already-processed mail is
# skipped before download, so it's cheap to repeat.
python agent.py --once

# Optional: narrow to the last N days AND clear the processed-cache for
# that window, forcing a re-ingest of those messages.
python agent.py --once --since 7d     # also accepts 12h, 30m, etc.
```

Keep the terminal open, or detach with `nohup` / `screen` / `tmux`:

```bash
nohup python agent.py --with-dashboard > /dev/null 2>&1 &
```

---

## Running 24/7 (macOS launchd)

The agent self-loops every `POLL_INTERVAL_SECONDS` (set it to `900` for a
15-minute cadence). To keep it alive across logins/crashes, run it as a
**LaunchAgent**.

`~/Library/LaunchAgents/com.yunison.email-agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.yunison.email-agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/ABSOLUTE/PATH/email-agent/.venv/bin/python</string>
        <string>/ABSOLUTE/PATH/email-agent/agent.py</string>
        <string>--with-dashboard</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/ABSOLUTE/PATH/email-agent</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key>
    <string>/ABSOLUTE/PATH/email-agent/agent.launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/ABSOLUTE/PATH/email-agent/agent.launchd.log</string>
</dict>
</plist>
```

Use **absolute paths** (launchd has no shell/PATH); use `.venv/bin/python`
directly (don't rely on an activated venv). Then:

```bash
launchctl load -w ~/Library/LaunchAgents/com.yunison.email-agent.plist   # start (+ at every login)
launchctl list | grep email-agent                                        # status: PID, last exit code
launchctl kickstart -k gui/$(id -u)/com.yunison.email-agent              # restart (after editing .env)
launchctl unload ~/Library/LaunchAgents/com.yunison.email-agent.plist    # stop
```

- `RunAtLoad` starts it at login; `KeepAlive` restarts it if it crashes.
- launchd's stdout/stderr → `agent.launchd.log`; the app's own rotating log →
  `agent.log`.
- **Sleep caveat:** launchd does **not** run while the Mac is asleep. It resumes
  on wake (the default whole-mailbox scan catches up). For true round-the-clock,
  prevent sleep (`caffeinate -s`, or Battery settings) or host on an always-on
  machine.

---

## Dashboard

If you didn't start the agent with `--with-dashboard`, run it in a second
terminal (with the venv active):

```bash
python dashboard/app.py
```

Then open <http://localhost:5050>. The **Emails** tab lists every named thread
with its keywords, briefing snippet, and a pending-action badge. Click a thread
to see the full HTML briefing. Auto-refreshes every 60s.

The **Invoices** tab at <http://localhost:5050/invoices> lists all extracted
invoices (amount, due date, company, link) ordered by received date.

Read-only — no write endpoints.

---

## Customising rules

Edit `rules.json` — partial matches are case-insensitive:

```json
{
  "thread_list": {
    "Draft SPA":  ["SPA", "share purchase agreement"],
    "Benten DD":  ["Benten", "due diligence", "DD"]
  },
  "invoice_groups": {
    "Accounting service for Benten": ["remi0813.at@gmail.com", "t-furukawa@oharalaw.jp"]
  }
}
```

- **`thread_list`** — a map of **named thread → list of subject keywords** for
  the **Emails** pipeline. A message joins a thread when its **Subject** contains
  one of the keywords (sender is ignored). Each thread keeps a single rolling
  briefing-note summary, shown under the thread name on the dashboard. A subject
  matching two threads goes to the first match.
- **`invoice_groups`** — a map of **named group → list of `From:` substrings**
  for the **Invoices** pipeline. Each matching message is scanned by the model for
  structured invoice fields, tagged with the group name, and stored in the
  `invoices` table.

### Hot-reload without restart

While the agent is running:

```bash
python agent.py --reload-rules
```

This sends `SIGUSR1` (via the PID file) to the live process; the new rules
are applied on the next poll cycle.

---

## CLI reference

| Command                                    | What it does |
|--------------------------------------------|--------------|
| `python agent.py`                          | Poll forever at `POLL_INTERVAL_SECONDS`. Scans the whole mailbox each cycle (processed mail skipped). |
| `python agent.py --once`                   | Single poll cycle then exit. |
| `python agent.py --with-dashboard`         | Also start the Flask UI on :5050. |
| `python agent.py --since 7d`               | Optional: narrow the lookback (also `12h`, `30m`) and clear the processed-cache for that window. Default is all time. |
| `python agent.py --reload-rules`           | Tell the running agent to re-read `rules.json`. |

---

## Project structure

```
├── agent.py            — main loop, signals, CLI entry
├── config.py           — loads .env + rules.json
├── filter_engine.py    — thread-group / invoice-sender matching
├── gmail_client.py     — Gmail OAuth + paginated message fetch
├── storage.py          — SQLite (thread_summaries, invoices, processed_messages, run_log)
├── summariser.py       — OpenAI prompts + JSON-shaped responses
├── rules.json          — editable filter rules (hot-reloadable)
├── dashboard/
│   ├── app.py          — Flask app (read-only)
│   └── templates/      — index.html, thread.html, invoices.html
└── credentials/        — OAuth client + token (gitignored)
```

See [CLAUDE.md](CLAUDE.md) for a deeper tour of the data model and
module-by-module behaviour.

---

## Files not in git (fresh checkout)

A clean `git clone` is missing a handful of files — secrets, runtime state,
and OAuth tokens are all gitignored. Here's what to do with each:

| File / directory | Where it comes from |
|---|---|
| `.env` | `cp .env.example .env`, then fill in real values (at minimum `OPENAI_API_KEY_EMAILS`). |
| `credentials/credentials.json` | **You** download this from Google Cloud Console — see [Setup → step 3](#3-enable-the-gmail-api). It cannot be regenerated by the agent. |
| `credentials/token.json` | Auto-created on first run after you complete the browser OAuth flow (`python agent.py --once`). |
| `agent.db` | Auto-created by SQLite the first time the agent runs. Delete it to wipe summaries; the OAuth token is unaffected. |
| `agent.log` | Auto-created by the rotating file handler. |
| `agent.pid` | Written while the agent is running, removed when it exits cleanly. Safe to delete if left behind by a crash. |

### Quickstart on a fresh clone

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
#   ↳ edit .env and set OPENAI_API_KEY_EMAILS / OPENAI_API_KEY_PDF

mkdir -p credentials
#   ↳ drop your downloaded OAuth client into credentials/credentials.json

python agent.py --once
#   ↳ browser opens for Google consent → token.json saved → agent.db created
```

After that initial run, every subsequent invocation is non-interactive.

---

## Troubleshooting

- **`re-auth needed` in the log** — delete `credentials/token.json` and run
  `python agent.py --once` to redo browser OAuth.
- **Nothing showing up** — confirm `rules.json` keywords/senders actually match
  your mail. The default run already scans the whole mailbox; if you previously
  processed mail under different rules, `--since 30d` clears that window's cache
  and forces a re-ingest.
- **JSON parse errors from the summariser** — calls use OpenAI JSON mode so
  replies are valid JSON; if one ever fails to parse, the raw text is stored
  verbatim so the dashboard still renders.
- **Gmail only returns ~100 messages** — make sure you didn't revert the
  pagination loop in `gmail_client.fetch_new_messages`; it must walk
  `nextPageToken` to completion.
