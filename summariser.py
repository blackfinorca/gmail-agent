import json
import logging

import anthropic

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a business correspondence assistant. Your job is to maintain a "
    "concise, always-current summary of an email thread. When given a new message, "
    "update the summary to incorporate the new information. Preserve: key decisions, "
    "dates, amounts, deadlines, and open action items. Remove outdated information "
    "superseded by newer messages. Be concise — maximum {max_tokens} words.\n\n"
    "Format the summary using HTML: use <h3> for section headings, <ul> and <li> for bullet points. "
    "Structure with sections like 'Overview', 'Key Timeline & Decisions', 'Key Terms Agreed', etc. "
    "Use bullets for lists of items.\n\n"
    "Also determine whose action is pending based on the latest message:\n"
    "- \"you\" — the recipient (account owner) needs to reply or act\n"
    "- \"them\" — waiting for the other party to reply or act\n"
    "- \"none\" — no action pending (FYI only, resolved, or informational)\n\n"
    "Respond with valid JSON only, no preamble, in this exact shape:\n"
    "{{\"summary\": \"...\", \"pending_action\": \"you\" | \"them\" | \"none\"}}"
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
        self.max_tokens = max_tokens

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
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text.strip()
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
            logger.error("Failed to parse summariser response: %s", e)
            # Fallback: treat raw text as summary
            return raw, "none"

    def initial_summary(self, message: dict) -> tuple:
        return self.update_summary("", message)

    def summarise_thread(self, messages: list) -> tuple:
        """Summarise an entire thread from scratch. Returns (summary, pending_action)."""
        system = (
            "You are a business correspondence assistant. Read the full email thread below "
            "and produce a concise, always-current summary. Preserve: key decisions, dates, "
            "amounts, deadlines, and open action items. Be concise — maximum "
            f"{self.max_tokens} words.\n\n"
            "Also determine whose action is pending based on the latest message:\n"
            "- \"you\" — the recipient (account owner) needs to reply or act\n"
            "- \"them\" — waiting for the other party to reply or act\n"
            "- \"none\" — no action pending (FYI only, resolved, or informational)\n\n"
            "Respond with valid JSON only, no preamble:\n"
            "{\"summary\": \"...\", \"pending_action\": \"you\" | \"them\" | \"none\"}"
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
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            raw = response.content[0].text.strip()
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
            logger.error("Failed to parse summariser response: %s", e)
            return raw, "none"


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
