import types

from summariser import Summariser


class _FakeCompletions:
    def __init__(self, text):
        self._text = text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        msg = types.SimpleNamespace(content=self._text)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])


class _FakeClient:
    """Mimics openai.OpenAI: client.chat.completions.create(...)."""
    def __init__(self, text):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(text))


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


def test_extract_invoice_parses_json_after_prose():
    # Model ignores "no preamble" and writes a sentence before the JSON block.
    s = _summariser(
        'This is an invoice. Here are the fields:\n```json\n'
        '{"is_invoice": true, "billed_to": "Yunison", "invoice_name": "FA fees", '
        '"company": "Schuon", "invoice_number": "21", "amount": "627,000 JPY", '
        '"payable_at": "", "link": ""}\n```'
    )
    out = s.extract_invoice({"sender": "x", "body_text": "y"})
    assert out["is_invoice"] is True
    assert out["invoice_number"] == "21"
    assert out["amount"] == "627,000 JPY"


def test_extract_invoice_includes_attachment_text():
    s = _summariser('{"is_invoice": false}')
    s.extract_invoice({
        "sender": "law@firm.jp", "body_text": "please find attached",
        "attachments_text": "--- inv.pdf ---\nTotal Amount Due 500,000 JPY",
    })
    # messages[0]=system, messages[1]=user (where the attachment text goes)
    sent = s.client.chat.completions.last_kwargs["messages"][1]["content"]
    assert "ATTACHMENTS" in sent
    assert "500,000 JPY" in sent
