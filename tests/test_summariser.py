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
