# Dual-Pipeline Rebuild — Emails + Invoices

**Date:** 2026-06-01
**Status:** Approved (design)

## Goal

Split the agent into two pipelines driven by `rules.json`:

1. **Emails** — existing per-sender rolling briefing-note summary, now driven by
   a `thread_list` of email addresses. (Behaviour unchanged; rule key renamed.)
2. **Invoices** — a new pipeline that scans a separate `invoice_senders` list,
   detects incoming invoices, and extracts structured fields into their own
   table and dashboard tab.

## Decisions (locked)

- **Invoice scope:** only senders in a dedicated `invoice_senders` list are
  scanned for invoices (not all incoming mail).
- **Emails view:** keep the current rolling per-sender summary; only rename the
  rule key `sender_whitelist` → `thread_list`.
- **Keywords:** dropped entirely.
- **`sent_at`:** the email received date. **`payable_at`:** the payment due date
  extracted from the invoice.
- **Invoice link:** URL extracted from the email body (`''` if none).
- **Dedupe key:** `invoice_number + sender`; rows with no invoice number fall
  back to the Gmail `message_id`.
- **Processed ledger:** invoices share the existing `processed_messages` ledger
  (single ledger). `--since` still forces a rescan.

## Changes by file

### `rules.json`
```json
{
  "thread_list":     ["core8eight@", "info@trackrecordtrading.com"],
  "invoice_senders": ["billing@stripe.com", "invoices@vendor.com"]
}
```
`keywords` and `sender_whitelist` removed.

### `config.py`
`FilterRules`: drop `keywords`, rename `sender_whitelist` → `thread_list`, add
`invoice_senders: list[str]`. `load_config()` reads both keys (default to `[]`).

### `filter_engine.py`
- `matches_thread(msg)` — case-insensitive substring of any `thread_list` entry
  in the sender header.
- `matches_invoice(msg)` — same against `invoice_senders`.
- `classify(msg)` — returns `sender:<entry>` for the thread rule. Keyword branch
  deleted.

### `storage.py` — new `invoices` table
```sql
CREATE TABLE IF NOT EXISTS invoices (
    invoice_key     TEXT PRIMARY KEY,   -- invoice_number+sender, else message_id
    message_id      TEXT,
    sender_email    TEXT,
    billed_to       TEXT,    -- "for who"
    invoice_name    TEXT,
    company         TEXT,
    invoice_number  TEXT,
    amount          TEXT,    -- raw, keep currency symbol
    sent_at         INTEGER, -- email received date (unix)
    payable_at      TEXT,    -- due date as extracted (formats vary)
    link            TEXT,    -- URL from body, '' if none
    created_at      INTEGER
);
```
New methods: `upsert_invoice(...)` (ON CONFLICT update), `get_all_invoices()`
ordered by `sent_at DESC`. `sender_summaries` table unchanged.

### `summariser.py` — add `extract_invoice(msg) -> dict`
Own system prompt + JSON shape; reuse `_extract_json()` fence-stripping. Returns:
```json
{"is_invoice": true, "billed_to": "...", "invoice_name": "...",
 "company": "...", "invoice_number": "...", "amount": "...",
 "payable_at": "...", "link": "..."}
```
`is_invoice=false` → caller skips the row (an invoice sender may also send
non-invoice mail). Existing summary methods untouched.

### `agent.py` — `run_once`
Same fetch + dedupe. After fetching, route each unprocessed message:
- **Thread pipeline:** messages whose sender matches `thread_list` → group by
  sender → `update_sender_summary` → `upsert_sender_summary` (current logic).
- **Invoice pipeline:** messages whose sender matches `invoice_senders` → per
  message `extract_invoice`; if `is_invoice`, build `invoice_key`
  (`f"{number}|{sender}"`, fallback `message_id`) → `upsert_invoice`.
- A message may match both lists; both pipelines run for it.
- Mark processed after both pipelines handle the message.
- `run_log`: count invoice extractions toward `llm_calls`.

### Dashboard
- Shared nav bar on both pages: **Emails** | **Invoices**.
- `GET /` — emails (current `index.html`, unchanged content).
- `GET /invoices` — new `invoices.html`; table columns:
  Sender · For · Invoice · Company · No. · Amount · Sent · Payable · Link.
- `GET /sender/<email>` — kept.

## Error handling

- Reuse existing patterns: `anthropic.APIError` → log, skip that message, retry
  next poll. JSON parse failure in `extract_invoice` → log raw, skip the invoice
  (do not write a partial row). Gmail/SQLite errors → log, continue, record in
  `run_log.errors`.

## Testing

- `filter_engine.py` `__main__` block: extend to exercise `matches_thread` and
  `matches_invoice`.
- `storage.py` `__main__` block: assert the `invoices` table is created.
- `summariser.py` `__main__` block: add a sample invoice email and print the
  extracted dict (requires `ANTHROPIC_API_KEY`).
- Manual: `python agent.py --once --since 7d` then check `/invoices`.

## Out of scope

- PDF/attachment parsing (link is body URL only).
- Editing or marking invoices paid from the dashboard (read-only).
- Multiple invoices per single email (one email → at most one invoice row).
