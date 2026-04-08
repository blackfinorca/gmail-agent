import logging

from config import FilterRules

logger = logging.getLogger(__name__)


class FilterEngine:
    def __init__(self, rules: FilterRules):
        self.rules = rules

    def matches(self, message: dict) -> bool:
        sender = message.get("sender", "").lower()
        subject = message.get("subject", "").lower()
        body = message.get("body_text", "").lower()

        for entry in self.rules.sender_whitelist:
            if entry.lower() in sender:
                return True

        haystack = subject + " " + body
        for kw in self.rules.keywords:
            if kw.lower() in haystack:
                return True

        return False

    def classify(self, message: dict) -> str:
        sender = message.get("sender", "").lower()
        subject = message.get("subject", "").lower()
        body = message.get("body_text", "").lower()

        for entry in self.rules.sender_whitelist:
            if entry.lower() in sender:
                return f"sender:{entry}"

        haystack = subject + " " + body
        for kw in self.rules.keywords:
            if kw.lower() in haystack:
                return f"keyword:{kw}"

        return "unmatched"


if __name__ == "__main__":
    from config import FilterRules

    rules = FilterRules(
        sender_whitelist=["billing@", "accounts@"],
        keywords=["invoice", "payment due"],
    )
    engine = FilterEngine(rules)

    test_messages = [
        {
            "sender": "billing@acme.com",
            "subject": "Your monthly statement",
            "body_text": "Please find your statement attached.",
        },
        {
            "sender": "friend@gmail.com",
            "subject": "Invoice #1234 for services",
            "body_text": "Hi, here is the invoice.",
        },
        {
            "sender": "spam@random.com",
            "subject": "Hello there",
            "body_text": "Just checking in.",
        },
    ]

    for msg in test_messages:
        matched = engine.matches(msg)
        rule = engine.classify(msg) if matched else "—"
        print(f"  [{msg['sender']}] matched={matched}  rule={rule}")
