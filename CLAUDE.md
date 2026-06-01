# Gmail Intelligence Agent — Project Context

This file is the canonical context for Claude Code working in this repo.
It describes **the code as it stands**, not the original build spec.

---

## What this project does

A Python agent that polls Gmail on a schedule and routes messages through
**two independent pipelines**:

1. **Emails pipeline** — `thread_list` is a map of **named thread → list of
   subject keywords**. A message joins a thread when its **Subject** contains
   one of the thread's keywords (case-insensitive substring; sender is
   ignored). All messages in a thread fold into **one rolling "briefing-note"
   summary per named thread**. Claude regenerates that summary every time a
   new batch arrives, preserving running context. A message whose subject
   matches two threads is assigned to the first match.

2. **Invoices pipeline** — `invoice_groups` is a map of **named group → list of
   sender substrings**. Messages from a group's senders are scanned per-message.
   Any **PDF attachments** (≤10MB) are downloaded and turned into text
   (`attachments.pdf_to_text`: pdfplumber, OCR fallback for scans) and fed to
   Claude alongside the email body. Claude detects whether each email is an
   invoice and, if so, extracts structured fields (invoice number, amount, due
   date, etc.) into a dedicated `invoices` table, tagged with its group name,
   shown on a separate dashboard tab.

A single message can hit both pipelines simultaneously. A small Flask dashboard
renders both tabs.

---

## Tech stack

| Layer        | Choice                              |
|--------------|-------------------------------------|
| Language     | Python 3.11+                        |
| Gmail        | `google-api-python-client` (OAuth)  |
| LLM          | `anthropic` SDK, `claude-sonnet-4-20250514` |
| Scheduler    | `schedule` + `time.sleep`           |
| Storage      | SQLite (single file, `agent.db`)    |
| Config       | `.env` + `rules.json`               |
| Web UI       | Flask + plain HTML/CSS              |
| Logging      | stdlib `logging` + rotating file    |

---

## Current file layout

```
email-agent/
├── CLAUDE.md               ← this file
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
├── rules.json              ← editable filter rules: thread_list + invoice_groups (hot-reloadable)
│
├── config.py               ← loads .env + rules.json → FilterRules
├── gmail_client.py         ← OAuth + paginated fetch + attachment download
├── attachments.py          ← PDF → text (pdfplumber, OCR fallback)
├── filter_engine.py        ← thread_for() / invoice_group_for()
├── summariser.py           ← Claude prompts, JSON-shaped responses
├── storage.py              ← SQLite: thread_summaries, invoices, processed_messages, run_log
├── agent.py                ← main loop, signals, CLI entry
│
├── dashboard/
│   ├── app.py              ← Flask routes
│   └── templates/
│       ├── index.html      ← named-thread list (Emails tab)
│       ├── thread.html     ← per-thread briefing detail
│       └── invoices.html   ← structured invoice list (Invoices tab)
│
└── credentials/            ← gitignored; OAuth client + token live here
```

---

## Data model (SQLite)

Four tables; all created on first run by `storage.Storage._init_db()`.

```sql
CREATE TABLE IF NOT EXISTS thread_summaries (
    thread_name     TEXT PRIMARY KEY,  -- the name from rules.json thread_list
    members         TEXT,              -- comma-joined subject keywords for the thread
    summary         TEXT,              -- HTML; see summariser format
    message_count   INTEGER DEFAULT 0,
    last_updated    INTEGER,           -- unix ts
    pending_action  TEXT DEFAULT 'none'   -- 'you' | 'them' | 'none'
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_key     TEXT PRIMARY KEY,
    message_id      TEXT,
    sender_email    TEXT,
    invoice_group   TEXT,              -- name from rules.json invoice_groups
    billed_to       TEXT,
    invoice_name    TEXT,
    company         TEXT,
    invoice_number  TEXT,
    amount          TEXT,
    sent_at         INTEGER,         -- unix ts of email received date
    payable_at      TEXT,            -- due date as extracted (text)
    link            TEXT,
    created_at      INTEGER
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
```

`invoice_key` dedup logic: `invoice_number|sender_email` when an invoice
number is present, otherwise falls back to `message_id`. `sent_at` is the
email's received date (unix); `payable_at` is the due date as text exactly
as extracted by Claude.

`processed_messages` is the dedupe ledger shared by both pipelines; `--since`
clears it for a chosen window so the agent can rescan.

---

## Module behaviour

### `config.py`
- `FilterRules` dataclass (`thread_list`, `invoice_groups`,
  `poll_interval_seconds`, `max_summary_tokens`). Both `thread_list` and
  `invoice_groups` are `dict[str, list[str]]` — `thread_list` maps a name to
  subject keywords, `invoice_groups` maps a name to sender substrings.
- `load_config()` reads `rules.json` for rules (`thread_list`,
  `invoice_groups`) and `.env` for intervals/tokens.

### `gmail_client.py`
- `GmailClient.authenticate()` — token refresh, falls back to browser OAuth
  on first run. Scope: `gmail.readonly`.
- `fetch_new_messages(since_ts)` — **paginates** `messages.list` (the early
  versions only fetched the first 100; the current code walks `nextPageToken`
  to completion), then `messages.get(format='full')` for each.
- `decode_body()` — prefers `text/plain`, strips quoted reply blocks.
- `_collect_attachments(payload)` — walks the MIME tree, returns metadata
  `{filename, mime_type, attachment_id, size}` for every file part (added to
  each parsed message under `"attachments"`).
- `download_attachment(message_id, attachment_id)` — fetches + base64url-decodes
  one attachment's bytes via the `attachments().get` endpoint.

### `attachments.py`
- `pdf_to_text(data: bytes) -> str` — digital text via `_pdfplumber_text`; if the
  result is under `MIN_TEXT_CHARS` (scanned PDF), falls back to `_ocr_text`
  (`pdf2image` + `pytesseract`). **Never raises** — returns `''` on total
  failure. Heavy libs are imported lazily so the module loads without them.
- OCR needs the `tesseract` and `poppler` **system binaries** (`brew install
  tesseract poppler`). Without them, scanned PDFs yield `''` (logged), digital
  PDFs still work.

### `filter_engine.py`
- `thread_for(msg)` — returns the **name** of the first `thread_list` thread
  whose keyword (case-insensitive substring) appears in the message **subject**,
  or `None` if the subject matches no thread.
- `invoice_group_for(msg)` — returns the **name** of the first `invoice_groups`
  group whose sender substring matches the `sender` field, or `None`.

### `summariser.py`
- Model: `claude-sonnet-4-20250514`.
- Claude sometimes wraps its JSON reply in ```` ```json ```` fences —
  `_extract_json()` strips them before `json.loads()`.
- `SYSTEM_PROMPT` uses `{max_tokens}` as a format placeholder, so the literal
  JSON braces in the prompt **must be escaped as `{{ }}`** — easy to break
  when editing. (See commit 332bde8.)
- `INVOICE_SYSTEM_PROMPT` is passed directly to the API without `.format()`,
  so its JSON braces are **single** (not doubled). Do not add `.format()` calls
  to it.
- Summary HTML follows a fixed shape: `<h3>TL;DR</h3>`, `<h3>Key Decisions &
  Agreements</h3>`, `<h3>Timeline & Deadlines</h3>`, `<h3>Open Items & Risks</h3>`,
  `<h3>Next Action</h3>`. Empty sections are omitted.
- Four entry points:
  - `update_summary(existing, msg)` — single-message update (legacy path).
  - `update_sender_summary(existing, batch)` — **the thread pipeline path**:
    folds a batch of new messages into the rolling thread summary (the method
    name is historical; it is key-agnostic). Returns
    `(summary: str, pending_action: str)`.
  - `summarise_thread(msgs)` — one-shot summarise a full thread.
  - `extract_invoice(msg) -> dict` — **the invoice pipeline path**: sends one
    message to Claude with `INVOICE_SYSTEM_PROMPT`. Includes `msg["attachments_text"]`
    (extracted PDF text) in the prompt when present. Returns `{"is_invoice": False}`
    for non-invoices or JSON parse failures; otherwise returns a dict with
    `is_invoice=True` and the extracted string fields (`billed_to`,
    `invoice_name`, `company`, `invoice_number`, `amount`, `payable_at`,
    `link`).

### `storage.py`
- `get_thread_summary`, `upsert_thread_summary` (atomic upsert keyed by
  `thread_name`; increments `message_count` by `message_count_delta` and
  refreshes `members`).
- `upsert_invoice`, `get_all_invoices()` — invoice CRUD; ordered by
  `sent_at DESC`. `get_all_invoices_grouped()` buckets them by `invoice_group`.
- `is_processed`, `mark_processed`, `clear_processed_since`.
- `get_all_thread_summaries()` — ordered by `last_updated DESC`.
- `get_last_run_timestamp()` — falls back to "24h ago" if `run_log` is empty.

### `agent.py`
- `Agent.run_once(since_override=None)`:
  1. Determine `since` (last run, or override).
  2. Fetch new Gmail messages.
  3. Skip already-processed; route surviving messages into two pipelines
     (a message can hit both if it matches both lists):
     - **Thread pipeline**: `thread_for(msg)` (subject keyword) → group messages
       by thread name → `update_sender_summary(batch)` → `upsert_thread_summary`
       (members = configured subject keywords) → `mark_processed`.
     - **Invoice pipeline**: `invoice_group_for(msg)` → `_extract_attachment_text`
       (download + `pdf_to_text` each PDF ≤10MB) → `extract_invoice(msg)` per
       message → if `is_invoice`, compute `_invoice_key` and `upsert_invoice`
       (tagged with the group name) → `mark_processed`.
  4. Append run stats to `run_log`.
- `run_forever(with_dashboard, since_override)`:
  - Prints a startup banner (shows both `thread_list` and `invoice_groups`),
    writes `agent.pid`.
  - Optionally starts the Flask dashboard in a daemon thread.
  - Installs a `SIGUSR1` handler that flips `_pending_reload` so rules can
    be re-read mid-loop without a restart.
- Static helpers: `_extract_email()` splits the address out of `"Name <addr>"`
  headers; `_invoice_key(invoice_number, sender_email, message_id)` builds the
  invoice dedup key; `_parse_date_to_ts(date_str)` parses RFC-2822 Date headers
  to unix timestamps; `_extract_attachment_text(gmail, msg)` downloads each PDF
  attachment (≤`MAX_ATTACHMENT_BYTES`) and runs `pdf_to_text` on it.

### CLI flags (`python agent.py …`)
| Flag                  | Effect |
|-----------------------|--------|
| _(none)_              | Run forever, poll every `POLL_INTERVAL_SECONDS`. |
| `--once`              | Single poll cycle, then exit. |
| `--with-dashboard`    | Also serve the Flask UI on `localhost:5050`. |
| `--reload-rules`      | Send `SIGUSR1` to the running agent (via `agent.pid`) — picks up `rules.json` immediately. |
| `--since 7d` (or `12h`, `30m`) | Override the lookback window and clear the processed-cache for that window so messages can be re-ingested. |

### `dashboard/app.py`
- `GET /` — `index.html`, named threads listed (name + members), auto-refresh
  every 60s.
- `GET /thread/<name>` — `thread.html`, full briefing for one named thread.
- `GET /invoices` — `invoices.html`, structured invoice list ordered by
  received date descending.
- Nav bar (Emails | Invoices) is present on all pages.
- Read-only; no write endpoints.

---

## Bootstrapping a fresh checkout

The following files are **gitignored** and will be missing on a clean clone.
When the user asks you to set the project up, or you hit a `FileNotFoundError`
for one of these, handle them as below — do **not** invent placeholder secrets
or skip the OAuth step.

| Missing file | Tier | How to create it |
|---|---|---|
| `.env` | auto | Copy `.env.example` → `.env`. Leave secret values as the placeholder strings and tell the user which keys still need real values (at minimum `ANTHROPIC_API_KEY`). Never invent or commit real keys. |
| `credentials/` (directory) | auto | `mkdir -p credentials` if missing. Also create `credentials/.gitkeep` if the directory is empty. |
| `credentials/credentials.json` | **user-only** | OAuth client secret. Cannot be generated — the user must download it from Google Cloud Console (see README). If missing, stop and ask the user to provide it; do not stub it out. |
| `credentials/token.json` | runtime | Auto-created by `gmail_client.GmailClient.authenticate()` on first run. Requires an interactive browser flow — only generated when the user runs `python agent.py --once` themselves. Do **not** try to run the OAuth flow non-interactively. |
| `agent.db` | runtime | Auto-created by `storage.Storage._init_db()` on first run — no action needed. To wipe state, just delete the file. |
| `agent.log` | runtime | Auto-created by the rotating file handler in `setup_logging()`. No action needed. |
| `agent.pid` | runtime | Auto-created by `run_forever()` while the agent is alive; removed in its `finally` block. If a stale one is left behind after a crash, it's safe to delete. |
| `rules.json` | code | Tracked in git. If it's somehow missing, `config.load_config()` raises `FileNotFoundError` — recreate with the schema in [README.md](README.md) (`thread_list` object of named threads → subject keywords + `invoice_groups` object of named groups → sender substrings) and ask the user which rules to populate. |

### Standard "fresh setup" sequence

When the user asks to set the project up from a fresh clone:

1. `cp .env.example .env` (only if `.env` is missing — never overwrite).
2. `mkdir -p credentials` if absent.
3. Check `credentials/credentials.json` exists. **If not, stop and ask the
   user** — they must download it from Google Cloud Console.
4. Tell the user to fill in `ANTHROPIC_API_KEY` in `.env`, then run
   `python agent.py --once` so the OAuth flow can write `token.json` and
   `storage.py` can create `agent.db`.
5. Do not try to run the agent yourself before the user has done the OAuth
   step — it will block on a browser prompt.

---

## Operational notes / gotchas

- **JSON-in-format-string trap**: `SYSTEM_PROMPT` is `.format()`-ed with
  `max_tokens`. Any literal `{` or `}` in the prompt must be doubled. The
  example JSON shape at the bottom of the prompt uses `{{ }}` for this reason.
- **Markdown fences from Claude**: occasionally the model wraps its JSON in
  ```` ```json … ``` ````. `_extract_json()` strips this; do not remove that
  helper.
- **OCR system binaries**: scanned-PDF extraction needs `tesseract` + `poppler`
  installed at the OS level (`brew install tesseract poppler`). They are NOT pip
  packages. Missing → scanned invoices extract `''` (logged, not fatal); digital
  PDFs still work via pdfplumber. `attachments.pdf_to_text` never raises.
- **Gmail pagination**: don't reintroduce a single `messages.list` call —
  it caps at 100. Loop on `nextPageToken`.
- **Hot rule reload**: editing `rules.json` does NOT auto-pick up until the
  next poll *after* `--reload-rules` is sent (or until the agent restarts).
- **`.env` and `credentials/`** are gitignored. `credentials/credentials.json`
  is the OAuth client; `credentials/token.json` is the user token after first
  consent.

---

## Common tasks

| Goal                                 | How |
|--------------------------------------|-----|
| Re-summarise the last week           | `python agent.py --once --since 7d` |
| Run with the dashboard               | `python agent.py --with-dashboard` |
| Update rules without restart         | edit `rules.json`, then `python agent.py --reload-rules` |
| Reset summaries (keep auth)          | delete `agent.db`; next run rebuilds from `--since` window |
| Inspect runs                         | `sqlite3 agent.db "select * from run_log order by run_at desc limit 20;"` |

---

## Error-handling expectations

- Gmail `HttpError` → log, continue, record in `run_log.errors`.
- `anthropic.APIError` → log and skip that sender batch (retry next poll).
- JSON parse failure from Claude → log the raw text, store it as-is with
  `pending_action='none'` (so the dashboard still shows *something*).
- SQLite write failure → log with traceback, do not crash the loop.
- Refresh-token failure → `google-auth` raises; the agent logs a clear
  "re-auth needed" message so you know to delete `token.json`.
