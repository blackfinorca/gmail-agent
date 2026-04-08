# Gmail Intelligence Agent — Claude Code Spec

> Drop this file into an empty project folder and run `claude` to start building.
> Claude Code will use this as its master instruction set.

---

## Project Goal

Build a Python agent that runs 24/7, monitors a Gmail account, filters emails by
sender address or keywords, and maintains a **distilled, always-current summary**
per conversation thread — so you can open a dashboard and instantly see the latest
state of any tracked correspondence (e.g. invoices, client threads, vendor comms).

---

## Tech Stack

| Layer        | Choice                        | Notes                                      |
|--------------|-------------------------------|--------------------------------------------|
| Language     | Python 3.11+                  |                                            |
| Gmail access | `google-api-python-client`    | OAuth 2.0, offline access                  |
| Scheduler    | `schedule` + `time.sleep`     | Simple poll loop, swap for APScheduler later |
| LLM          | Anthropic SDK (`anthropic`)   | Claude claude-sonnet-4-20250514 for summaries         |
| Storage      | SQLite via `sqlite3`          | Single file DB, no infra needed            |
| Config       | `.env` via `python-dotenv`    | All secrets in env vars, never hardcoded   |
| Web UI       | `Flask` + plain HTML/JS       | Minimal dashboard to read summaries        |
| Logging      | Python `logging` module       | Rotating file handler + console            |

---

## Project Structure to Create

```
gmail-agent/
├── CLAUDE.md               ← this file
├── .env.example            ← template for secrets (no real values)
├── .gitignore
├── requirements.txt
├── README.md
│
├── config.py               ← loads .env, defines FilterRules dataclass
├── gmail_client.py         ← Gmail API auth + fetch logic
├── filter_engine.py        ← rule matching (sender, keywords)
├── summariser.py           ← Anthropic API calls, prompt logic
├── storage.py              ← SQLite CRUD for summaries + run log
├── agent.py                ← main poll loop, orchestration
│
├── dashboard/
│   ├── app.py              ← Flask app, routes
│   └── templates/
│       ├── index.html      ← list of tracked threads + summaries
│       └── thread.html     ← single thread detail view
│
└── credentials/            ← gitignored, holds OAuth token files
    └── .gitkeep
```

---

## Module Specs

### `config.py`
- Load all config from `.env` using `python-dotenv`
- Define a `FilterRules` dataclass:
  ```python
  @dataclass
  class FilterRules:
      sender_whitelist: list[str]   # e.g. ["vendor@acme.com", "@client.com"]
      keywords: list[str]           # e.g. ["invoice", "contract", "PO", "payment due"]
      poll_interval_seconds: int    # default: 300 (5 min)
      max_summary_tokens: int       # default: 400
  ```
- Load rules from a `rules.json` file so they can be changed without touching code
- Expose a `load_config()` function that returns a `FilterRules` instance

---

### `gmail_client.py`
- Implement `GmailClient` class
- Auth method: `authenticate()` — uses `credentials/token.json`, auto-refreshes,
  falls back to browser OAuth flow on first run. Scopes: `gmail.readonly`
- Fetch method: `fetch_new_messages(since_timestamp: int) -> list[dict]`
  - Calls `messages.list` with query: `after:{since_timestamp}`
  - For each message ID, calls `messages.get` with `format=full`
  - Returns list of dicts with fields: `id`, `thread_id`, `sender`, `subject`,
    `date`, `body_text` (decoded from base64, plain text preferred over HTML),
    `snippet`
- Helper: `decode_body(payload) -> str` — handles multipart MIME, prefers
  `text/plain`, strips quoted reply blocks (lines starting with `>`)

---

### `filter_engine.py`
- `FilterEngine(rules: FilterRules)` class
- `matches(message: dict) -> bool` method:
  - Returns `True` if sender email contains any entry in `sender_whitelist`
    (partial match, so `@acme.com` matches any acme address)
  - OR if subject or body contains any keyword from `keywords` list
    (case-insensitive)
- `classify(message: dict) -> str` — returns the matched rule label
  (e.g. `"keyword:invoice"` or `"sender:vendor@acme.com"`) for logging

---

### `summariser.py`
- `Summariser(api_key: str, max_tokens: int)` class
- Core method: `update_summary(existing_summary: str, new_message: dict) -> str`
  - Calls Claude API with this prompt structure:

    ```
    System:
    You are a business correspondence assistant. Your job is to maintain a
    concise, always-current summary of an email thread. When given a new message,
    update the summary to incorporate the new information. Preserve: key decisions,
    dates, amounts, deadlines, and open action items. Remove outdated information
    superseded by newer messages. Be concise — maximum {max_tokens} words.
    Respond with only the updated summary text, no preamble.

    User:
    CURRENT SUMMARY:
    {existing_summary or "No summary yet."}

    NEW MESSAGE:
    From: {sender}
    Date: {date}
    Subject: {subject}
    ---
    {body_text}
    ---

    Update the summary to include the key points from this new message.
    ```

  - Returns the updated summary string
- `initial_summary(message: dict) -> str` — same as above but for first message
  in a thread (no existing summary)

---

### `storage.py`
- `Storage(db_path: str)` class, initialises SQLite on first run
- Schema:

  ```sql
  CREATE TABLE IF NOT EXISTS threads (
      thread_id       TEXT PRIMARY KEY,
      sender          TEXT,
      subject         TEXT,
      summary         TEXT,
      message_count   INTEGER DEFAULT 0,
      last_updated    INTEGER,   -- unix timestamp
      matched_rule    TEXT
  );

  CREATE TABLE IF NOT EXISTS processed_messages (
      message_id  TEXT PRIMARY KEY,
      thread_id   TEXT,
      processed_at INTEGER
  );

  CREATE TABLE IF NOT EXISTS run_log (
      id              INTEGER PRIMARY KEY AUTOINCREMENT,
      run_at          INTEGER,
      messages_seen   INTEGER,
      messages_matched INTEGER,
      llm_calls       INTEGER,
      errors          TEXT
  );
  ```

- Methods:
  - `get_summary(thread_id) -> dict | None`
  - `upsert_summary(thread_id, sender, subject, summary, matched_rule)`
  - `is_processed(message_id) -> bool`
  - `mark_processed(message_id, thread_id)`
  - `log_run(run_at, messages_seen, matched, llm_calls, errors)`
  - `get_all_threads() -> list[dict]` — for dashboard, ordered by `last_updated DESC`
  - `get_last_run_timestamp() -> int` — used to set Gmail `after:` query param

---

### `agent.py`
- `Agent` class that wires everything together
- `run_once()` method — one full poll cycle:
  1. Get `last_run_timestamp` from storage (default: 24h ago on first run)
  2. Fetch new messages from Gmail since that timestamp
  3. For each message: check if already processed → if not, run filter
  4. For matched messages: load existing summary, call summariser, upsert result,
     mark message as processed
  5. Log the run stats
- `run_forever()` method — calls `run_once()` on schedule, catches and logs all
  exceptions without crashing (agent must be resilient)
- Entry point: `if __name__ == "__main__": Agent().run_forever()`
- Print a startup banner showing config: poll interval, active rules, db path

---

### `dashboard/app.py`
- Flask app with two routes:
  - `GET /` — renders `index.html` with all threads from `storage.get_all_threads()`,
    sorted by most recently updated. Show: sender, subject, last updated, message
    count, first 120 chars of summary
  - `GET /thread/<thread_id>` — renders `thread.html` with full summary for one thread
- Auto-refresh meta tag on index page: refresh every 60 seconds
- Run on `localhost:5050`
- Dashboard is **read-only** — no write operations

---

### `dashboard/templates/index.html`
- Clean, minimal HTML (no framework needed)
- Dark background (`#0f1117`), monospace font for summaries
- Table or card list of threads
- Each row: coloured badge for matched rule type, sender, subject, relative
  timestamp ("2 hours ago"), snippet of summary, link to full thread view
- Add a small stats bar at top: total threads tracked, last agent run timestamp

---

## `.env.example` to Create

```env
# Gmail OAuth — generate via Google Cloud Console
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here

# Anthropic
ANTHROPIC_API_KEY=your_key_here

# Agent config
POLL_INTERVAL_SECONDS=300
MAX_SUMMARY_TOKENS=400
DB_PATH=./agent.db
CREDENTIALS_DIR=./credentials
LOG_FILE=./agent.log
```

---

## `rules.json` to Create

```json
{
  "sender_whitelist": [
    "billing@",
    "accounts@",
    "invoice@"
  ],
  "keywords": [
    "invoice",
    "purchase order",
    "PO#",
    "payment due",
    "contract",
    "statement",
    "overdue",
    "reminder"
  ]
}
```

---

## `requirements.txt` to Create

```
anthropic>=0.25.0
google-api-python-client>=2.120.0
google-auth-httplib2>=0.2.0
google-auth-oauthlib>=1.2.0
python-dotenv>=1.0.0
schedule>=1.2.0
flask>=3.0.0
```

---

## `README.md` to Create

Include:
1. **Setup** — Google Cloud Console steps to enable Gmail API and download `credentials.json`
2. **First run** — `python agent.py` triggers browser OAuth, saves `token.json`
3. **Running agent** — `python agent.py` (keep terminal open or use `nohup`/`screen`)
4. **Running dashboard** — `python dashboard/app.py` in a second terminal
5. **Customising rules** — edit `rules.json`, no restart needed on next poll cycle

---

## Error Handling Rules

- All Gmail API calls: catch `HttpError`, log and continue (don't crash)
- All Anthropic calls: catch `APIError`, log and skip that message (retry next poll)
- If a message body can't be decoded: use `snippet` field as fallback
- SQLite write failures: log with full traceback, continue run
- Token expiry: `google-auth` handles refresh automatically; if refresh fails, log
  clearly that re-auth is needed

---

## Build Order for Claude Code

Build in this sequence — each step is independently testable:

1. `requirements.txt`, `.env.example`, `rules.json`, `.gitignore`
2. `config.py` — test: `python config.py` prints loaded rules
3. `storage.py` — test: `python storage.py` creates DB and prints schema
4. `gmail_client.py` — test: `python gmail_client.py` authenticates and prints 5 recent subjects
5. `filter_engine.py` — test with mock messages
6. `summariser.py` — test with a hardcoded sample email
7. `agent.py` — full loop, single `run_once()` then exit, check DB
8. `dashboard/app.py` + templates — verify UI shows stored summaries
9. `README.md`
