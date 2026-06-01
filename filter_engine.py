from __future__ import annotations

import logging

from config import FilterRules

logger = logging.getLogger(__name__)


class FilterEngine:
    def __init__(self, rules: FilterRules):
        self.rules = rules

    def thread_for(self, message: dict) -> str | None:
        """Return the name of the first thread whose subject keyword appears in
        the message subject, or None if the message belongs to no thread."""
        subject = message.get("subject", "").lower()
        for name, keywords in self.rules.thread_list.items():
            for kw in keywords:
                if kw.lower() in subject:
                    return name
        return None

    def invoice_group_for(self, message: dict) -> str | None:
        """Return the name of the first invoice group whose sender substring
        matches the sender, or None if the message belongs to no group."""
        sender = message.get("sender", "").lower()
        for name, emails in self.rules.invoice_groups.items():
            for entry in emails:
                if entry.lower() in sender:
                    return name
        return None

    def gmail_query(self) -> str:
        """Build a Gmail search query so the server returns only candidate
        messages (thread subject keywords OR invoice-group senders), instead of
        downloading the whole mailbox to filter locally. Empty string if no
        rules are configured."""
        clauses = []
        for keywords in self.rules.thread_list.values():
            for kw in keywords:
                clauses.append(f'subject:"{kw}"')
        for emails in self.rules.invoice_groups.values():
            for entry in emails:
                # Invoices arrive as PDFs — require one server-side so we don't
                # download/LLM-classify every email from a chatty sender. MUST be
                # parenthesised: in a bare `a OR b has:attachment` chain Gmail
                # applies has:attachment to the whole query, starving subject
                # (thread) matches.
                clauses.append(f"(from:{entry} has:attachment filename:pdf)")
        return " OR ".join(clauses)


if __name__ == "__main__":
    rules = FilterRules(
        thread_list={"Draft SPA": ["SPA", "share purchase"]},
        invoice_groups={"Accounting": ["invoices@vendor.com"]},
    )
    engine = FilterEngine(rules)

    test_messages = [
        {"sender": "lawyer@firm.com", "subject": "Re: Draft SPA v3", "body_text": ""},
        {"sender": "invoices@vendor.com", "subject": "Invoice #12", "body_text": ""},
        {"sender": "spam@random.com", "subject": "Hello", "body_text": ""},
    ]
    for msg in test_messages:
        print(
            f"  [{msg['sender']}] thread={engine.thread_for(msg)} "
            f"invoice_group={engine.invoice_group_for(msg)}"
        )
