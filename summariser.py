import json
import logging
import os
import re

from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)

# Override with OPENAI_MODEL in .env. gpt-4o-mini is ~$0.15/M in, $0.60/M out.
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def _extract_json(text: str) -> str:
    """Return the bare JSON string from a model reply.

    JSON mode already yields a clean object, but this stays defensive: it strips
    ```json fences and slices out the object if any prose surrounds it."""
    text = (text or "").strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    # If prose surrounds the object, slice from the first { to the last }.
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]
    return text.strip()

SYSTEM_PROMPT = (
"You are a senior management consultant writing briefing notes for a C-suite executive. "
"Your job is to maintain a concise, always-current summary of an email thread. "
"When given a new message, update the summary to incorporate new information. "
"Remove anything superseded by newer messages.\n\n"

"WRITING STYLE:\n"
"- Lead with conclusions, not context.\n"
"- Every bullet must carry a fact, number, date, name, or decision — no filler.\n"
"- Use plain language. No corporate hedging. No passive voice.\n"
"- Maximum {max_tokens} words total.\n\n"

"FORMAT (HTML only, no inline styles):\n"
"<h3>TL;DR</h3> — 1–2 sentence situation summary. What is this thread about and where does it stand right now.\n"
"<h3>Key Decisions & Agreements</h3> — Bullet each confirmed decision. Include who agreed, date if known.\n"
"<h3>Timeline & Deadlines</h3> — Chronological bullets. Dates + what is due or what happened.\n"
"<h3>Open Items & Risks</h3> — What is unresolved, disputed, or at risk. Flag blockers explicitly.\n"
"<h3>Next Action</h3> — Single sentence: who does what by when.\n\n"
"Omit any section that has no content — do not include empty headings.\n\n"

"PENDING ACTION — classify whose move it is based on the latest message:\n"
"- 'you' — the account owner needs to reply or act\n"
"- 'them' — waiting on the other party\n"
"- 'none' — informational, resolved, or no action required\n\n"

"Respond with valid JSON only. No preamble. Exact shape:\n"
"{{\"summary\": \"<h3>TL;DR</h3>...\", \"pending_action\": \"you\" | \"them\" | \"none\"}}"
)

INVOICE_SYSTEM_PROMPT = (
    "You are an accounts-payable assistant. Decide whether the email below is an "
    "invoice or a payment request, and if so extract its fields. If it is NOT an "
    "invoice (newsletter, marketing, a plain receipt/confirmation with nothing due, "
    "general correspondence), return is_invoice false and leave the other fields empty.\n\n"
    "Extract:\n"
    "- billed_to: the customer the invoice is billed TO (the 'Invoice for' / "
    "'Bill to' party). Prefer the organisation name over an individual contact "
    "or job title. This is NOT the issuer.\n"
    "- invoice_name: the invoice title or a short description of the services\n"
    "- company: the business ISSUING the invoice (the payee / 'Invoice from')\n"
    "- invoice_number: the invoice/reference number only — strip any label like "
    "'Invoice No:' (e.g. '250', not 'Invoice No: 250'). '' if none\n"
    "- amount: the TOTAL amount payable INCLUDING tax (the grand 'Total' / "
    "'Total payable'), NOT the pre-tax subtotal. Keep the currency code/symbol "
    "(e.g. '275,000 JPY'). '' if none\n"
    "- payable_at: the payment due date exactly as written ('' if none)\n"
    "- link: the URL to view or pay the invoice from the email body ('' if none)\n\n"
    "EXAMPLE — an invoice issued by 'ATSUNORI TSUJIMURA CPA & CPTA', addressed to "
    "'Yunison Pte Ltd', titled 'Due Diligence Services (Down Payment)', Invoice "
    "No: 250, subtotal 250,000 + 10% tax = Total 275,000 JPY, Due Date 2026/05/08 "
    "maps to:\n"
    '{"is_invoice": true, "billed_to": "Yunison Pte Ltd", '
    '"invoice_name": "Due Diligence Services (Down Payment)", '
    '"company": "ATSUNORI TSUJIMURA CPA & CPTA", "invoice_number": "250", '
    '"amount": "275,000 JPY", "payable_at": "2026/05/08", "link": ""}\n\n'
    "Respond with valid JSON only. No preamble. Exact shape:\n"
    '{"is_invoice": true, "billed_to": "", "invoice_name": "", "company": "", '
    '"invoice_number": "", "amount": "", "payable_at": "", "link": ""}'
)

USER_TEMPLATE = """\
CURRENT SUMMARY:
{existing_summary}

NEW MESSAGE:
From: {sender}
Date: {date}
Subject: {subject}
---
{body_text}
---

Update the summary and determine whose action is pending.\
"""


class Summariser:
    def __init__(self, api_key: str, max_tokens: int = 400):
        self.client = OpenAI(api_key=api_key)
        self.max_tokens = max_tokens          # word-count hint in prompt
        self._api_max_tokens = max(1200, max_tokens * 3)  # actual API response budget

    def _chat(self, system: str, user: str) -> str:
        """One JSON-mode chat call. Returns the raw response content string.
        Raises OpenAIError on API failure (caller decides what to do)."""
        response = self.client.chat.completions.create(
            model=MODEL,
            max_tokens=self._api_max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content

    def _summarise(self, system: str, user: str) -> tuple:
        """Run a summary call and return (summary, pending_action)."""
        try:
            raw = _extract_json(self._chat(system, user))
            data = json.loads(raw)
            summary = (data.get("summary") or "").strip()
            pending_action = data.get("pending_action", "none")
            if pending_action not in ("you", "them", "none"):
                pending_action = "none"
            return summary, pending_action
        except OpenAIError as e:
            logger.error("OpenAI API error: %s", e)
            raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse summariser response: %s | raw=%r", e, locals().get("raw", ""))
            return locals().get("raw", ""), "none"

    def update_summary(self, existing_summary: str, new_message: dict) -> tuple:
        """Returns (summary: str, pending_action: str)."""
        system = SYSTEM_PROMPT.format(max_tokens=self.max_tokens)
        user = USER_TEMPLATE.format(
            existing_summary=existing_summary or "No summary yet.",
            sender=new_message.get("sender", ""),
            date=new_message.get("date", ""),
            subject=new_message.get("subject", ""),
            body_text=new_message.get("body_text", "") or new_message.get("snippet", ""),
        )
        return self._summarise(system, user)

    def initial_summary(self, message: dict) -> tuple:
        return self.update_summary("", message)

    def update_sender_summary(self, existing_summary: str, new_messages: list[dict]) -> tuple:
        """Update a per-sender one-pager with a batch of new messages. Returns (summary, pending_action)."""
        system = SYSTEM_PROMPT.format(max_tokens=self.max_tokens)

        msgs_text = ""
        for i, msg in enumerate(new_messages, 1):
            msgs_text += (
                f"--- Message {i} ---\n"
                f"From: {msg.get('sender', '')}\n"
                f"Date: {msg.get('date', '')}\n"
                f"Subject: {msg.get('subject', '')}\n\n"
                f"{msg.get('body_text', '') or msg.get('snippet', '')}\n\n"
            )

        user = (
            f"CURRENT SUMMARY:\n{existing_summary or 'No summary yet.'}\n\n"
            f"NEW MESSAGES ({len(new_messages)}):\n{msgs_text}"
            "Update the summary to reflect all new messages above, then determine whose action is pending."
        )
        return self._summarise(system, user)

    def summarise_thread(self, messages: list) -> tuple:
        """Summarise an entire thread from scratch. Returns (summary, pending_action)."""
        system = (
            "You are a business correspondence assistant. Read the full email thread below "
            "and produce a concise, always-current summary. Preserve: key decisions, dates, "
            "amounts, deadlines, and open action items. Be concise — maximum "
            f"{self.max_tokens} words.\n\n"
            "Format the summary using HTML: use <ul> and <li> for bullet points, "
            "<strong> for emphasis on key figures, dates, or amounts. "
            "Group related points under a short plain-text label followed by a <ul>. "
            "Do not use <h3> or large headings — keep it compact.\n\n"
            "Also determine whose action is pending based on the latest message:\n"
            "- \"you\" — the recipient (account owner) needs to reply or act\n"
            "- \"them\" — waiting for the other party to reply or act\n"
            "- \"none\" — no action pending (FYI only, resolved, or informational)\n\n"
            "Respond with valid JSON only, no preamble:\n"
            "{\"summary\": \"<ul><li>...</li></ul>\", \"pending_action\": \"you\" | \"them\" | \"none\"}"
        )

        thread_text = ""
        for i, msg in enumerate(messages, 1):
            thread_text += (
                f"--- Message {i} ---\n"
                f"From: {msg.get('sender', '')}\n"
                f"Date: {msg.get('date', '')}\n"
                f"Subject: {msg.get('subject', '')}\n\n"
                f"{msg.get('body_text', '') or msg.get('snippet', '')}\n\n"
            )

        user = f"FULL THREAD:\n\n{thread_text}\nSummarise this thread and determine whose action is pending."
        return self._summarise(system, user)

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
        )
        attachments_text = message.get("attachments_text", "")
        if attachments_text:
            user += (
                "ATTACHMENTS (text extracted from PDF files on this email — the "
                "invoice itself is usually here):\n"
                f"{attachments_text}\n---\n"
            )
        user += "Is this an invoice? If so, extract the fields."

        try:
            raw = _extract_json(self._chat(INVOICE_SYSTEM_PROMPT, user))
            data = json.loads(raw)
        except OpenAIError as e:
            logger.error("OpenAI API error (invoice): %s", e)
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY in .env to test the summariser.")
    else:
        s = Summariser(api_key=api_key, max_tokens=400)
        sample = {
            "sender": "billing@acme.com",
            "date": "Mon, 1 Apr 2026 09:00:00 +0000",
            "subject": "Invoice #4521 — Payment Due 15 Apr 2026",
            "body_text": (
                "Dear Customer,\n\n"
                "Please find attached Invoice #4521 for $3,200 for consulting services "
                "in March 2026. Payment is due by 15 April 2026.\n\n"
                "Bank transfer details are on the invoice.\n\nThank you."
            ),
        }
        print("Summary:\n", s.initial_summary(sample))
