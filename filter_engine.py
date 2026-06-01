from __future__ import annotations

import logging

from config import FilterRules

logger = logging.getLogger(__name__)


class FilterEngine:
    def __init__(self, rules: FilterRules):
        self.rules = rules

    def thread_for(self, message: dict) -> str | None:
        """Return the name of the first thread group whose member address
        matches the sender, or None if the message belongs to no thread."""
        sender = message.get("sender", "").lower()
        for name, emails in self.rules.thread_list.items():
            for entry in emails:
                if entry.lower() in sender:
                    return name
        return None

    def matches_invoice(self, message: dict) -> bool:
        sender = message.get("sender", "").lower()
        for entry in self.rules.invoice_senders:
            if entry.lower() in sender:
                return True
        return False


if __name__ == "__main__":
    rules = FilterRules(
        thread_list={"Vendors": ["billing@", "accounts@"]},
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
            f"  [{msg['sender']}] thread={engine.thread_for(msg)} "
            f"invoice={engine.matches_invoice(msg)}"
        )
