# Emails + Invoices Dual-Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the agent into two `rules.json`-driven pipelines — an Emails tab (rolling per-sender summary, key renamed to `thread_list`) and a new Invoices tab that extracts structured invoice fields from a dedicated `invoice_senders` list.

**Architecture:** Reuse the existing fetch + dedupe-ledger loop. After fetching, each unprocessed message is routed to the thread pipeline (matches `thread_list`), the invoice pipeline (matches `invoice_senders`), or ignored. Thread pipeline is unchanged. Invoice pipeline LLM-extracts fields per message into a new `invoices` table, deduped by `invoice_number+sender`. Dashboard gains an `/invoices` route and a shared nav bar.

**Tech Stack:** Python 3.11+, SQLite, `anthropic` SDK (`claude-sonnet-4-20250514`), Flask. Tests via `pytest` (newly added) — pure/mockable logic only; LLM calls are mocked, Gmail is not exercised in tests.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `rules.json` | modify | `thread_list` + `invoice_senders`; drop `keywords`/`sender_whitelist` |
| `config.py` | modify | `FilterRules` fields renamed/added |
| `filter_engine.py` | modify | `matches_thread`, `matches_invoice`, `classify` |
| `storage.py` | modify | `invoices` table, `upsert_invoice`, `get_all_invoices` |
| `summariser.py` | modify | `extract_invoice(msg)` |
| `agent.py` | modify | two-pipeline routing in `run_once`, `_invoice_key`, `_parse_date_to_ts` |
| `dashboard/app.py` | modify | `/invoices` route, invoice time formatting |
| `dashboard/templates/invoices.html` | create | invoices table |
| `dashboard/templates/index.html` | modify | nav bar |
| `dashboard/templates/sender.html` | modify | nav bar |
| `requirements.txt` | modify | add `pytest` |
| `tests/conftest.py` | create | repo root on `sys.path` |
| `tests/test_filter.py` | create | filter routing tests |
| `tests/test_storage.py` | create | invoice storage tests |
| `tests/test_summariser.py` | create | `extract_invoice` parsing (mocked client) |
| `tests/test_agent.py` | create | `_invoice_key`, `_parse_date_to_ts` |
| `tests/test_dashboard.py` | create | `/invoices` route via Flask test client |
| `CLAUDE.md` / `README.md` | modify | document the two pipelines |

---

## Task 0: Test harness setup

**Files:**
- Modify: `requirements.txt`
- Create: `tests/conftest.py`

- [ ] **Step 1: Add pytest to requirements**

Append to `requirements.txt`:

```
pytest>=8.0.0
```

- [ ] **Step 2: Install it**

Run: `pip install -r requirements.txt`
Expected: pytest installs successfully.

- [ ] **Step 3: Create `tests/conftest.py`**

Modules are top-level (e.g. `import config`), so the repo root must be importable from `tests/`.

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 4: Verify pytest collects nothing yet**

Run: `pytest -q`
Expected: `no tests ran` (exit 5) — confirms collection works.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/conftest.py
git commit -m "test: add pytest harness and conftest path shim"
```

---

## Task 1: Config — `thread_list` + `invoice_senders`

**Files:**
- Modify: `config.py:13-34`
- Modify: `rules.json`

- [ ] **Step 1: Rewrite `FilterRules` and `load_config` in `config.py`**

Replace lines 13–34 (the `@dataclass` and `load_config`) with:

```python
@dataclass
class FilterRules:
    thread_list: list[str] = field(default_factory=list)
    invoice_senders: list[str] = field(default_factory=list)
    poll_interval_seconds: int = 300
    max_summary_tokens: int = 400


def load_config(rules_path: str = "rules.json") -> FilterRules:
    rules_file = Path(rules_path)
    if not rules_file.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_path}")

    with open(rules_file) as f:
        data = json.load(f)

    return FilterRules(
        thread_list=data.get("thread_list", []),
        invoice_senders=data.get("invoice_senders", []),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", 300)),
        max_summary_tokens=int(os.getenv("MAX_SUMMARY_TOKENS", 400)),
    )
```

- [ ] **Step 2: Update the `__main__` block in `config.py:37-43`**

Replace the print lines that reference `sender_whitelist`/`keywords`:

```python
if __name__ == "__main__":
    config = load_config()
    print("Loaded FilterRules:")
    print(f"  thread_list      : {config.thread_list}")
    print(f"  invoice_senders  : {config.invoice_senders}")
    print(f"  poll_interval    : {config.poll_interval_seconds}s")
    print(f"  max_summary_tokens: {config.max_summary_tokens}")
```

- [ ] **Step 3: Rewrite `rules.json`**

```json
{
  "thread_list": [
    "core8eight@",
    "info@trackrecordtrading.com",
    "hello@moby.co",
    "contact@stockanalysis.com"
  ],
  "invoice_senders": [
    "billing@stripe.com",
    "invoices@vendor.com"
  ]
}
```

- [ ] **Step 4: Smoke-test config load**

Run: `python config.py`
Expected: prints `thread_list` and `invoice_senders` with the values above, no traceback.

- [ ] **Step 5: Commit**

```bash
git add config.py rules.json
git commit -m "feat: replace sender_whitelist/keywords with thread_list + invoice_senders"
```

---

## Task 2: Filter engine — two match methods

**Files:**
- Modify: `filter_engine.py`
- Create: `tests/test_filter.py`

- [ ] **Step 1: Write the failing tests in `tests/test_filter.py`**

```python
from config import FilterRules
from filter_engine import FilterEngine


def make(thread, inv):
    return FilterEngine(FilterRules(thread_list=thread, invoice_senders=inv))


def test_matches_thread():
    e = make(["info@track"], [])
    assert e.matches_thread({"sender": "Info <info@trackrecord.com>", "subject": "", "body_text": ""}) is True
    assert e.matches_thread({"sender": "x@other.com", "subject": "", "body_text": ""}) is False


def test_matches_invoice():
    e = make([], ["billing@stripe.com"])
    assert e.matches_invoice({"sender": "Stripe <billing@stripe.com>", "subject": "", "body_text": ""}) is True
    assert e.matches_invoice({"sender": "x@other.com", "subject": "", "body_text": ""}) is False


def test_classify_thread():
    e = make(["info@track"], [])
    assert e.classify({"sender": "info@trackrecord.com", "subject": "", "body_text": ""}) == "sender:info@track"


def test_classify_unmatched():
    e = make(["info@track"], [])
    assert e.classify({"sender": "x@other.com", "subject": "", "body_text": ""}) == "unmatched"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_filter.py -q`
Expected: FAIL — `FilterEngine` has no `matches_thread`/`matches_invoice`; `FilterRules` has no `thread_list`/`invoice_senders` (the latter passes after Task 1, but `matches_thread` still fails).

- [ ] **Step 3: Replace the `FilterEngine` body in `filter_engine.py:8-42`**

```python
class FilterEngine:
    def __init__(self, rules: FilterRules):
        self.rules = rules

    def matches_thread(self, message: dict) -> bool:
        sender = message.get("sender", "").lower()
        for entry in self.rules.thread_list:
            if entry.lower() in sender:
                return True
        return False

    def matches_invoice(self, message: dict) -> bool:
        sender = message.get("sender", "").lower()
        for entry in self.rules.invoice_senders:
            if entry.lower() in sender:
                return True
        return False

    def classify(self, message: dict) -> str:
        sender = message.get("sender", "").lower()
        for entry in self.rules.thread_list:
            if entry.lower() in sender:
                return f"sender:{entry}"
        return "unmatched"
```

- [ ] **Step 4: Update the `__main__` block in `filter_engine.py:45-75`**

```python
if __name__ == "__main__":
    rules = FilterRules(
        thread_list=["billing@", "accounts@"],
        invoice_senders=["invoices@vendor.com"],
    )
    engine = FilterEngine(rules)

    test_messages = [
        {"sender": "billing@acme.com", "subject": "Statement", "body_text": ""},
        {"sender": "invoices@vendor.com", "subject": "Invoice", "body_text": ""},
        {"sender": "spam@random.com", "subject": "Hello", "body_text": ""},
    ]
    for msg in test_messages:
        print(
            f"  [{msg['sender']}] thread={engine.matches_thread(msg)} "
            f"invoice={engine.matches_invoice(msg)} rule={engine.classify(msg)}"
        )
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_filter.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add filter_engine.py tests/test_filter.py
git commit -m "feat: split filter into matches_thread and matches_invoice"
```

---

## Task 3: Storage — `invoices` table

**Files:**
- Modify: `storage.py:9-34` (schema), add methods after `get_all_sender_summaries` (`storage.py:101`)
- Create: `tests/test_storage.py`

- [ ] **Step 1: Write the failing tests in `tests/test_storage.py`**

```python
from storage import Storage


def _invoice_kwargs(**overrides):
    base = dict(
        invoice_key="4521|billing@v.com",
        message_id="m1",
        sender_email="billing@v.com",
        billed_to="Acme",
        invoice_name="March consulting",
        company="Vendor Co",
        invoice_number="4521",
        amount="$3,200",
        sent_at=1000,
        payable_at="15 Apr 2026",
        link="http://x",
    )
    base.update(overrides)
    return base


def test_upsert_invoice_and_get(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs())
    rows = s.get_all_invoices()
    assert len(rows) == 1
    assert rows[0]["invoice_number"] == "4521"
    assert rows[0]["amount"] == "$3,200"


def test_upsert_invoice_dedupes_on_key(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs(amount="$100"))
    s.upsert_invoice(**_invoice_kwargs(amount="$200"))
    rows = s.get_all_invoices()
    assert len(rows) == 1
    assert rows[0]["amount"] == "$200"


def test_get_all_invoices_orders_by_sent_at_desc(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="a", sent_at=100))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="b", sent_at=200))
    rows = s.get_all_invoices()
    assert [r["invoice_key"] for r in rows] == ["b", "a"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_storage.py -q`
Expected: FAIL — `Storage` has no `upsert_invoice`/`get_all_invoices`.

- [ ] **Step 3: Add the `invoices` table to `SCHEMA` in `storage.py`**

Insert this block inside the `SCHEMA` string (after the `run_log` table, before the closing `"""` at line 34):

```sql

CREATE TABLE IF NOT EXISTS invoices (
    invoice_key     TEXT PRIMARY KEY,
    message_id      TEXT,
    sender_email    TEXT,
    billed_to       TEXT,
    invoice_name    TEXT,
    company         TEXT,
    invoice_number  TEXT,
    amount          TEXT,
    sent_at         INTEGER,
    payable_at      TEXT,
    link            TEXT,
    created_at      INTEGER
);
```

- [ ] **Step 4: Add `upsert_invoice` and `get_all_invoices` after `get_all_sender_summaries` (`storage.py:101`)**

```python
    # --- Invoices ---

    def upsert_invoice(
        self,
        invoice_key: str,
        message_id: str,
        sender_email: str,
        billed_to: str,
        invoice_name: str,
        company: str,
        invoice_number: str,
        amount: str,
        sent_at: int,
        payable_at: str,
        link: str,
    ):
        now = int(time.time())
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO invoices
                    (invoice_key, message_id, sender_email, billed_to, invoice_name,
                     company, invoice_number, amount, sent_at, payable_at, link, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(invoice_key) DO UPDATE SET
                    message_id     = excluded.message_id,
                    sender_email   = excluded.sender_email,
                    billed_to      = excluded.billed_to,
                    invoice_name   = excluded.invoice_name,
                    company        = excluded.company,
                    invoice_number = excluded.invoice_number,
                    amount         = excluded.amount,
                    sent_at        = excluded.sent_at,
                    payable_at     = excluded.payable_at,
                    link           = excluded.link
                """,
                (invoice_key, message_id, sender_email, billed_to, invoice_name,
                 company, invoice_number, amount, sent_at, payable_at, link, now),
            )

    def get_all_invoices(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM invoices ORDER BY sent_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_storage.py -q`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add storage.py tests/test_storage.py
git commit -m "feat: add invoices table with upsert_invoice and get_all_invoices"
```

---

## Task 4: Summariser — `extract_invoice`

**Files:**
- Modify: `summariser.py` (add prompt constant + method)
- Create: `tests/test_summariser.py`

- [ ] **Step 1: Write the failing tests in `tests/test_summariser.py`**

```python
import types

from summariser import Summariser


class _FakeMessages:
    def __init__(self, text):
        self._text = text

    def create(self, **kwargs):
        return types.SimpleNamespace(content=[types.SimpleNamespace(text=self._text)])


class _FakeClient:
    def __init__(self, text):
        self.messages = _FakeMessages(text)


def _summariser(text):
    s = Summariser(api_key="test-key", max_tokens=400)
    s.client = _FakeClient(text)
    return s


def test_extract_invoice_parses_fields():
    s = _summariser(
        '{"is_invoice": true, "billed_to": "Acme Inc", "invoice_name": "March consulting", '
        '"company": "Vendor Co", "invoice_number": "4521", "amount": "$3,200", '
        '"payable_at": "15 April 2026", "link": "https://pay.example.com/4521"}'
    )
    out = s.extract_invoice({"sender": "billing@v.com", "date": "", "subject": "Invoice 4521", "body_text": "..."})
    assert out["is_invoice"] is True
    assert out["invoice_number"] == "4521"
    assert out["amount"] == "$3,200"
    assert out["link"] == "https://pay.example.com/4521"


def test_extract_invoice_non_invoice():
    s = _summariser('{"is_invoice": false}')
    out = s.extract_invoice({"sender": "news@v.com", "body_text": "newsletter"})
    assert out["is_invoice"] is False


def test_extract_invoice_strips_code_fences():
    s = _summariser('```json\n{"is_invoice": false}\n```')
    out = s.extract_invoice({"sender": "x", "body_text": "y"})
    assert out["is_invoice"] is False


def test_extract_invoice_bad_json_returns_not_invoice():
    s = _summariser("this is not json")
    out = s.extract_invoice({"sender": "x", "body_text": "y"})
    assert out["is_invoice"] is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_summariser.py -q`
Expected: FAIL — `Summariser` has no `extract_invoice`.

- [ ] **Step 3: Add the invoice prompt constant after `SYSTEM_PROMPT` (`summariser.py:45`)**

This prompt uses NO `.format()`, so literal JSON braces are written single (not doubled).

```python
INVOICE_SYSTEM_PROMPT = (
    "You are an accounts-payable assistant. Decide whether the email below is an "
    "invoice or a payment request, and if so extract its fields. If it is NOT an "
    "invoice (newsletter, marketing, a plain receipt/confirmation with nothing due, "
    "general correspondence), return is_invoice false and leave the other fields empty.\n\n"
    "Extract:\n"
    "- billed_to: the person or company the invoice is addressed to\n"
    "- invoice_name: a short title or description of what the invoice is for\n"
    "- company: the company issuing the invoice\n"
    "- invoice_number: the invoice or reference number ('' if none)\n"
    "- amount: total amount due, keep the currency symbol ('' if none)\n"
    "- payable_at: the payment due date exactly as written ('' if none)\n"
    "- link: the URL to view or pay the invoice from the email body ('' if none)\n\n"
    "Respond with valid JSON only. No preamble. Exact shape:\n"
    '{"is_invoice": true, "billed_to": "", "invoice_name": "", "company": "", '
    '"invoice_number": "", "amount": "", "payable_at": "", "link": ""}'
)
```

- [ ] **Step 4: Add the `extract_invoice` method to the `Summariser` class (after `summarise_thread`, `summariser.py:195`)**

```python
    def extract_invoice(self, message: dict) -> dict:
        """Detect + extract a single invoice from one email.

        Returns {"is_invoice": False} for non-invoices or parse failures,
        otherwise a dict with the extracted string fields.
        """
        user = (
            f"From: {message.get('sender', '')}\n"
            f"Date: {message.get('date', '')}\n"
            f"Subject: {message.get('subject', '')}\n"
            "---\n"
            f"{message.get('body_text', '') or message.get('snippet', '')}\n"
            "---\n"
            "Is this an invoice? If so, extract the fields."
        )

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=self._api_max_tokens,
                system=INVOICE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user}],
            )
            raw = _extract_json(response.content[0].text)
            data = json.loads(raw)
        except anthropic.APIError as e:
            logger.error("Anthropic API error (invoice): %s", e)
            raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse invoice response: %s | raw=%r", e, locals().get("raw", ""))
            return {"is_invoice": False}

        if not data.get("is_invoice"):
            return {"is_invoice": False}

        return {
            "is_invoice": True,
            "billed_to": (data.get("billed_to") or "").strip(),
            "invoice_name": (data.get("invoice_name") or "").strip(),
            "company": (data.get("company") or "").strip(),
            "invoice_number": (data.get("invoice_number") or "").strip(),
            "amount": (data.get("amount") or "").strip(),
            "payable_at": (data.get("payable_at") or "").strip(),
            "link": (data.get("link") or "").strip(),
        }
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_summariser.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add summariser.py tests/test_summariser.py
git commit -m "feat: add extract_invoice to summariser"
```

---

## Task 5: Agent — two-pipeline routing

**Files:**
- Modify: `agent.py` (add `_invoice_key`, `_parse_date_to_ts`, rewrite routing block in `run_once`)
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write the failing tests in `tests/test_agent.py`**

```python
from email.utils import parsedate_to_datetime

from agent import Agent


def test_invoice_key_with_number():
    assert Agent._invoice_key("4521", "billing@v.com", "msgid") == "4521|billing@v.com"


def test_invoice_key_fallback_to_message_id():
    assert Agent._invoice_key("", "billing@v.com", "msgid") == "msgid"
    assert Agent._invoice_key("   ", "billing@v.com", "msgid") == "msgid"


def test_parse_date_to_ts_valid():
    s = "Mon, 1 Apr 2026 09:00:00 +0000"
    assert Agent._parse_date_to_ts(s) == int(parsedate_to_datetime(s).timestamp())


def test_parse_date_to_ts_invalid_falls_back():
    ts = Agent._parse_date_to_ts("not a date")
    assert isinstance(ts, int) and ts > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_agent.py -q`
Expected: FAIL — `Agent` has no `_invoice_key`/`_parse_date_to_ts`.

- [ ] **Step 3: Add the two static helpers after `_extract_display_name` (`agent.py:82`)**

```python
    @staticmethod
    def _invoice_key(invoice_number: str, sender_email: str, message_id: str) -> str:
        """Dedupe key: invoice_number+sender, else fall back to message_id."""
        num = (invoice_number or "").strip()
        if num:
            return f"{num}|{sender_email}"
        return message_id

    @staticmethod
    def _parse_date_to_ts(date_str: str) -> int:
        """Parse an RFC-2822 email Date header to a unix ts; fall back to now."""
        from email.utils import parsedate_to_datetime
        try:
            return int(parsedate_to_datetime(date_str).timestamp())
        except (TypeError, ValueError):
            return int(time.time())
```

- [ ] **Step 4: Replace the routing + processing block in `run_once` (`agent.py:108-149`)**

Replace from the comment `# Group unprocessed, matched messages by sender email` through the end of the sender `for` loop (the `except` that appends `f"sender:{sender_email} — {e}"`) with:

```python
        # Route unprocessed messages into the two pipelines
        sender_batches: dict[str, list] = {}
        invoice_msgs: list = []
        for msg in messages:
            if self.storage.is_processed(msg["id"]):
                continue
            if self.filter.matches_thread(msg):
                sender_email = self._extract_email(msg["sender"])
                sender_batches.setdefault(sender_email, []).append(msg)
            if self.filter.matches_invoice(msg):
                invoice_msgs.append(msg)

        messages_matched = sum(len(v) for v in sender_batches.values()) + len(invoice_msgs)

        # --- Thread pipeline: rolling per-sender summary ---
        for sender_email, batch in sender_batches.items():
            rule = self.filter.classify(batch[0])
            display_name = self._extract_display_name(batch[0]["sender"])
            logger.info("Processing %d message(s) from %s (rule: %s)", len(batch), sender_email, rule)

            try:
                existing = self.storage.get_sender_summary(sender_email)
                existing_summary = existing["summary"] if existing else ""

                new_summary, pending_action = self.summariser.update_sender_summary(
                    existing_summary, batch
                )
                llm_calls += 1

                for msg in batch:
                    self.storage.mark_processed(msg["id"], msg["thread_id"])

                self.storage.upsert_sender_summary(
                    sender_email=sender_email,
                    display_name=display_name,
                    summary=new_summary,
                    matched_rule=rule,
                    pending_action=pending_action,
                    message_count_delta=len(batch),
                )
                logger.info("Sender summary updated for %s (%d new messages)", sender_email, len(batch))

            except Exception as e:
                logger.error("Error processing sender %s: %s", sender_email, e)
                errors.append(f"sender:{sender_email} — {e}")

        # --- Invoice pipeline: structured extraction per message ---
        for msg in invoice_msgs:
            sender_email = self._extract_email(msg["sender"])
            try:
                data = self.summariser.extract_invoice(msg)
                llm_calls += 1
                self.storage.mark_processed(msg["id"], msg["thread_id"])

                if not data.get("is_invoice"):
                    logger.info("Message %s from %s is not an invoice — skipped", msg["id"], sender_email)
                    continue

                key = self._invoice_key(data["invoice_number"], sender_email, msg["id"])
                self.storage.upsert_invoice(
                    invoice_key=key,
                    message_id=msg["id"],
                    sender_email=sender_email,
                    billed_to=data["billed_to"],
                    invoice_name=data["invoice_name"],
                    company=data["company"],
                    invoice_number=data["invoice_number"],
                    amount=data["amount"],
                    sent_at=self._parse_date_to_ts(msg.get("date", "")),
                    payable_at=data["payable_at"],
                    link=data["link"],
                )
                logger.info("Invoice stored: %s from %s", key, sender_email)

            except Exception as e:
                logger.error("Error processing invoice from %s: %s", sender_email, e)
                errors.append(f"invoice:{sender_email} — {e}")
```

> Note: a message matching both lists runs both pipelines; `mark_processed` is `INSERT OR IGNORE`, so the duplicate call is harmless.

- [ ] **Step 5: Update the startup banner in `run_forever` (`agent.py:187-188`)**

Replace the two lines printing `Sender rules`/`Keywords`:

```python
        print(f"  Thread senders : {self.config.thread_list}")
        print(f"  Invoice senders: {self.config.invoice_senders}")
```

- [ ] **Step 6: Run tests to verify pass**

Run: `pytest tests/test_agent.py -q`
Expected: 4 passed.

- [ ] **Step 7: Byte-compile to catch syntax errors in the rewritten block**

Run: `python -m py_compile agent.py`
Expected: no output (success).

- [ ] **Step 8: Commit**

```bash
git add agent.py tests/test_agent.py
git commit -m "feat: route messages into thread + invoice pipelines in run_once"
```

---

## Task 6: Dashboard — `/invoices` route + nav tabs

**Files:**
- Modify: `dashboard/app.py`
- Create: `dashboard/templates/invoices.html`
- Modify: `dashboard/templates/index.html:73` (add nav)
- Modify: `dashboard/templates/sender.html` (add nav)
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test in `tests/test_dashboard.py`**

```python
import importlib


def test_invoices_route_renders_invoice(tmp_path, monkeypatch):
    import storage as storage_mod

    db = str(tmp_path / "t.db")
    s = storage_mod.Storage(db)
    s.upsert_invoice(
        invoice_key="4521|b@v.com", message_id="m1", sender_email="b@v.com",
        billed_to="Acme", invoice_name="March consulting", company="Vendor Co",
        invoice_number="4521", amount="$3,200", sent_at=1000,
        payable_at="15 Apr 2026", link="https://pay.example.com/4521",
    )

    monkeypatch.setenv("DB_PATH", db)
    import dashboard.app as appmod
    importlib.reload(appmod)  # re-instantiate storage against the temp DB

    client = appmod.app.test_client()
    resp = client.get("/invoices")
    assert resp.status_code == 200
    assert b"4521" in resp.data
    assert b"Vendor Co" in resp.data
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_dashboard.py -q`
Expected: FAIL — no `/invoices` route (404).

- [ ] **Step 3: Add the `/invoices` route to `dashboard/app.py` (after `sender_detail`, line 55)**

```python
@app.route("/invoices")
def invoices():
    rows = storage.get_all_invoices()
    for r in rows:
        r["sent_display"] = relative_time(r.get("sent_at", 0))
    return render_template("invoices.html", invoices=rows, total=len(rows))
```

- [ ] **Step 4: Create `dashboard/templates/invoices.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="60">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Invoices — Gmail Intelligence Agent</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0f1117; color: #c9d1d9;
      font-family: 'Courier New', Courier, monospace; font-size: 14px;
      padding: 24px; max-width: 1100px;
    }
    h1 { color: #58a6ff; font-size: 20px; margin-bottom: 4px; }
    nav { margin: 12px 0 24px; display: flex; gap: 16px; }
    nav a { color: #8b949e; text-decoration: none; padding-bottom: 4px; }
    nav a:hover { color: #58a6ff; }
    nav a.active { color: #c9d1d9; border-bottom: 2px solid #58a6ff; }
    table { width: 100%; border-collapse: collapse; }
    th {
      text-align: left; color: #8b949e; border-bottom: 1px solid #21262d;
      padding: 8px 10px; font-weight: normal; text-transform: uppercase;
      font-size: 11px; letter-spacing: 0.05em;
    }
    td { padding: 10px; border-bottom: 1px solid #161b22; vertical-align: top; }
    tr:hover td { background: #161b22; }
    .amount { color: #3fb950; white-space: nowrap; }
    .num { color: #8b949e; }
    a.link { color: #58a6ff; text-decoration: none; }
    a.link:hover { text-decoration: underline; }
    .meta { color: #8b949e; font-size: 12px; white-space: nowrap; }
    .empty { text-align: center; color: #8b949e; padding: 60px 0; }
  </style>
</head>
<body>
  <h1>Invoices</h1>
  <nav>
    <a href="/">Emails</a>
    <a href="/invoices" class="active">Invoices</a>
  </nav>

  {% if invoices %}
  <table>
    <thead>
      <tr>
        <th>Sender</th><th>For</th><th>Invoice</th><th>Company</th>
        <th>No.</th><th>Amount</th><th>Sent</th><th>Payable</th><th>Link</th>
      </tr>
    </thead>
    <tbody>
      {% for v in invoices %}
      <tr>
        <td>{{ v.sender_email }}</td>
        <td>{{ v.billed_to }}</td>
        <td>{{ v.invoice_name }}</td>
        <td>{{ v.company }}</td>
        <td class="num">{{ v.invoice_number }}</td>
        <td class="amount">{{ v.amount }}</td>
        <td class="meta">{{ v.sent_display }}</td>
        <td class="meta">{{ v.payable_at }}</td>
        <td>{% if v.link %}<a class="link" href="{{ v.link }}" target="_blank" rel="noopener">view</a>{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <div class="empty">No invoices yet. The agent will populate this as invoice emails arrive.</div>
  {% endif %}
</body>
</html>
```

- [ ] **Step 5: Add the nav bar to `index.html` immediately after `<h1>...</h1>` (`index.html:73`)**

Insert after the `<h1>Gmail Intelligence Agent</h1>` line:

```html
  <nav style="margin:12px 0 24px; display:flex; gap:16px;">
    <a href="/" style="color:#c9d1d9; text-decoration:none; border-bottom:2px solid #58a6ff; padding-bottom:4px;">Emails</a>
    <a href="/invoices" style="color:#8b949e; text-decoration:none; padding-bottom:4px;">Invoices</a>
  </nav>
```

- [ ] **Step 6: Add the same nav bar to `sender.html`**

Open `dashboard/templates/sender.html`, find the first heading/back-link near the top of `<body>`, and insert the same `<nav>` block right after `<body>` opens (before existing content):

```html
  <nav style="margin:12px 0 24px; display:flex; gap:16px;">
    <a href="/" style="color:#8b949e; text-decoration:none; padding-bottom:4px;">Emails</a>
    <a href="/invoices" style="color:#8b949e; text-decoration:none; padding-bottom:4px;">Invoices</a>
  </nav>
```

- [ ] **Step 7: Run the dashboard test to verify pass**

Run: `pytest tests/test_dashboard.py -q`
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add dashboard/app.py dashboard/templates/invoices.html dashboard/templates/index.html dashboard/templates/sender.html tests/test_dashboard.py
git commit -m "feat: add invoices dashboard tab and nav bar"
```

---

## Task 7: Full suite + docs

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Run the whole test suite**

Run: `pytest -q`
Expected: all tests pass (filter 4, storage 3, summariser 4, agent 4, dashboard 1 = 16 passed).

- [ ] **Step 2: Update `CLAUDE.md`**

Make these edits to reflect the rebuild:
- Replace the "one rolling summary per sender" framing intro with: two pipelines — Emails (`thread_list`, rolling per-sender summary) and Invoices (`invoice_senders`, structured extraction).
- In the `rules.json` description, replace `sender_whitelist`/`keywords` with `thread_list` and `invoice_senders`.
- Add an `invoices` table block to the Data model section (copy the schema from Task 3 Step 3).
- Under `summariser.py`, add `extract_invoice(msg)` to the entry-points list.
- Under `agent.py` `run_once`, document the thread/invoice split (Task 5).
- Under `dashboard/app.py`, add the `GET /invoices` route.

- [ ] **Step 3: Update `README.md`**

- Replace the `rules.json` schema example (`sender_whitelist` + `keywords`) with `thread_list` + `invoice_senders`.
- Add one line noting the Invoices tab at `localhost:5050/invoices`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document Emails + Invoices dual-pipeline rebuild"
```

---

## Self-Review notes

- **Spec coverage:** `thread_list`/`invoice_senders` (T1), drop keywords (T1, T2), `invoices` table with all 11 spec fields (T3), `extract_invoice` with `is_invoice` skip + `_extract_json` reuse (T4), dedupe key `number+sender` fallback message_id (T5 `_invoice_key`), `sent_at`=email date / `payable_at`=due date (T5 `_parse_date_to_ts` + upsert), link from body (T4 prompt), both-pipeline routing + shared processed ledger (T5), `/invoices` route + nav tabs + 9 columns (T6), docs (T7). All covered.
- **Type consistency:** `extract_invoice` returns keys `is_invoice, billed_to, invoice_name, company, invoice_number, amount, payable_at, link`; `upsert_invoice` consumes exactly those plus `invoice_key, message_id, sender_email, sent_at`. `_invoice_key(invoice_number, sender_email, message_id)` signature matches the call in T5 Step 4.
- **Error handling:** `extract_invoice` swallows parse errors → `{"is_invoice": False}` (no partial rows); per-sender and per-invoice `try/except` append to `run_log.errors`; matches existing patterns.
