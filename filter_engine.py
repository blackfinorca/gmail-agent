import logging

from config import FilterRules

logger = logging.getLogger(__name__)


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
