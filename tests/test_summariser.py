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
    s = Summariser(emails_api_key="test-key", max_tokens=400)
    # Same canned client for both paths so either can be inspected.
    s.email_client = _FakeClient(text)
    s.pdf_client = _FakeClient(text)
    return s


def test_extract_invoice_parses_fields():
    s = _summariser(
        '{"is_invoice": true, "billed_to": "Acme Inc", "invoice_name": "March consulting", '
        '"company": "Vendor Co", "invoice_number": "4521", "amount": "$3,200", '
        '"payable_at": "15 April 2026", "link": "https://pay.example.com/4521"}'
    )
    out = s.extract_invoice(
        {"sender": "billing@v.com", "date": "", "subject": "Invoice 4521", "body_text": "..."},
        pdf_files=[("inv.pdf", b"%PDF-bytes")],
    )
    assert out["is_invoice"] is True
    assert out["invoice_number"] == "4521"
    assert out["amount"] == "$3,200"
    assert out["link"] == "https://pay.example.com/4521"


def test_extract_invoice_sends_pdf_as_file_part():
    s = _summariser('{"is_invoice": false}')
    s.extract_invoice(
        {"sender": "law@firm.jp", "body_text": "please find attached"},
        pdf_files=[("inv.pdf", b"%PDF-1.4 data")],
    )
    content = s.pdf_client.chat.completions.last_kwargs["messages"][1]["content"]
    # content is a list: a text part + one file part per PDF
    kinds = [part["type"] for part in content]
    assert "text" in kinds and "file" in kinds
    file_part = next(p for p in content if p["type"] == "file")
    assert file_part["file"]["filename"] == "inv.pdf"
    assert file_part["file"]["file_data"].startswith("data:application/pdf;base64,")


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


def test_summary_uses_email_client():
    s = _summariser('{"summary": "<h3>TL;DR</h3> ok", "pending_action": "you"}')
    summary, pa = s.update_sender_summary("", [{"sender": "a@b.com", "subject": "hi", "body_text": "x"}])
    assert pa == "you"
    assert "TL;DR" in summary
    assert s.email_client.chat.completions.last_kwargs is not None
