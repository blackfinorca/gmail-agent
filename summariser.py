import json
import logging
import re

import anthropic

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """Strip markdown code fences and return the bare JSON string."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ``` wrappers
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
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
        self.client = anthropic.Anthropic(api_key=api_key)
        self.max_tokens = max_tokens          # word-count hint in prompt
        self._api_max_tokens = max(1200, max_tokens * 3)  # actual API response budget

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

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=self._api_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = _extract_json(response.content[0].text)
            data = json.loads(raw)
            summary = data.get("summary", "").strip()
            pending_action = data.get("pending_action", "none")
            if pending_action not in ("you", "them", "none"):
                pending_action = "none"
            return summary, pending_action
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse summariser response: %s | raw=%r", e, locals().get("raw", ""))
            return locals().get("raw", ""), "none"

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

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=self._api_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = _extract_json(response.content[0].text)
            data = json.loads(raw)
            summary = data.get("summary", "").strip()
            pending_action = data.get("pending_action", "none")
            if pending_action not in ("you", "them", "none"):
                pending_action = "none"
            return summary, pending_action
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse summariser response: %s | raw=%r", e, locals().get("raw", ""))
            return locals().get("raw", ""), "none"

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

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=self._api_max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = _extract_json(response.content[0].text)
            data = json.loads(raw)
            summary = data.get("summary", "").strip()
            pending_action = data.get("pending_action", "none")
            if pending_action not in ("you", "them", "none"):
                pending_action = "none"
            return summary, pending_action
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            raise
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Failed to parse summariser response: %s | raw=%r", e, locals().get("raw", ""))
            return locals().get("raw", ""), "none"


if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY in .env to test the summariser.")
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
        summary = s.initial_summary(sample)
        print("Summary:\n", summary)
