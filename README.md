# Gmail Intelligence Agent

A Python agent that polls a Gmail account, filters messages by sender or
keyword rules, and maintains an always-current **one-pager briefing per
sender** — rendered in a small local Flask dashboard.

Summaries are written by Claude (`claude-sonnet-4-20250514`) in a fixed
briefing-note format: TL;DR, key decisions, timeline, open items, next action.
Each sender also has a `pending_action` flag (`you` / `them` / `none`) so you
can see at a glance who owes whom a reply.

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set ANTHROPIC_API_KEY
```

`.env` keys:

| Key                       | Default            | Notes |
|---------------------------|--------------------|-------|
| `ANTHROPIC_API_KEY`       | _(required)_       | Claude API key |
| `POLL_INTERVAL_SECONDS`   | `300`              | How often the agent polls Gmail |
| `MAX_SUMMARY_TOKENS`      | `400`              | Word-count hint passed to Claude |
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

# One poll, then exit (handy for cron or testing)
python agent.py --once

# Backfill / rescan the last N days (clears the processed-message cache
# for that window so messages get re-ingested)
python agent.py --once --since 7d     # also accepts 12h, 30m, etc.
```

Keep the terminal open, or detach with `nohup` / `screen` / `tmux`:

```bash
nohup python agent.py --with-dashboard > /dev/null 2>&1 &
```

---

## Dashboard

If you didn't start the agent with `--with-dashboard`, run it in a second
terminal (with the venv active):

```bash
python dashboard/app.py
```

Then open <http://localhost:5050>. The index page lists every tracked sender
grouped together, with the briefing snippet and a pending-action badge.
Click a sender to see the full HTML briefing. Auto-refreshes every 60s.
Read-only — no write endpoints.

---

## Customising rules

Edit `rules.json` — partial matches are case-insensitive:

```json
{
  "sender_whitelist": ["billing@", "accounts@", "@acme.com"],
  "keywords": ["invoice", "purchase order", "payment due", "contract"]
}
```

- **`sender_whitelist`** — substring match against the `From:` header
  (e.g. `"@acme.com"` matches any sender at that domain).
- **`keywords`** — case-insensitive substring match against subject + body.

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
| `python agent.py`                          | Poll forever at `POLL_INTERVAL_SECONDS`. |
| `python agent.py --once`                   | Single poll cycle then exit. |
| `python agent.py --with-dashboard`         | Also start the Flask UI on :5050. |
| `python agent.py --since 7d`               | Override the lookback window (also `12h`, `30m`). Clears processed-cache for that window. |
| `python agent.py --reload-rules`           | Tell the running agent to re-read `rules.json`. |

---

## Project structure

```
├── agent.py            — main loop, signals, CLI entry
├── config.py           — loads .env + rules.json
├── filter_engine.py    — sender / keyword matching
├── gmail_client.py     — Gmail OAuth + paginated message fetch
├── storage.py          — SQLite (sender_summaries, processed_messages, run_log)
├── summariser.py       — Claude prompts + JSON-shaped responses
├── rules.json          — editable filter rules (hot-reloadable)
├── dashboard/
│   ├── app.py          — Flask app (read-only)
│   └── templates/      — index.html, sender.html
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
| `.env` | `cp .env.example .env`, then fill in real values (at minimum `ANTHROPIC_API_KEY`). |
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
#   ↳ edit .env and set ANTHROPIC_API_KEY (and any other values you want to change)

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
- **No senders showing up** — confirm `rules.json` actually matches recent
  mail. A `--since 7d` rescan is the fastest way to verify.
- **JSON parse errors from the summariser** — Claude occasionally wraps its
  response in ```` ```json ``` ```` fences; the code strips them, but if you
  see one slip through, the raw text is stored verbatim so the dashboard
  still renders.
- **Gmail only returns ~100 messages** — make sure you didn't revert the
  pagination loop in `gmail_client.fetch_new_messages`; it must walk
  `nextPageToken` to completion.
