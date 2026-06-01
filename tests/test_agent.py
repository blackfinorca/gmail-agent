from email.utils import parsedate_to_datetime

from agent import Agent


class _FakeGmail:
    def __init__(self):
        self.downloaded = []

    def download_attachment(self, message_id, attachment_id):
        self.downloaded.append((message_id, attachment_id))
        return b"%PDF-bytes"


def test_invoice_key_with_number():
    assert Agent._invoice_key("4521", "billing@v.com", "msgid") == "4521|billing@v.com"


def test_invoice_key_fallback_to_message_id():
    assert Agent._invoice_key("", "billing@v.com", "msgid") == "msgid"
    assert Agent._invoice_key("   ", "billing@v.com", "msgid") == "msgid"


def test_parse_date_to_ts_valid():
    s = "Mon, 1 Apr 2026 09:00:00 +0000"
    assert Agent._parse_date_to_ts(s) == int(parsedate_to_datetime(s).timestamp())


def test_parse_date_to_ts_invalid_falls_back():
    ts = Agent._parse_date_to_ts("not a date")
    assert isinstance(ts, int) and ts > 0


def test_download_pdfs_returns_filename_bytes():
    gmail = _FakeGmail()
    msg = {"id": "m1", "attachments": [
        {"filename": "inv.pdf", "mime_type": "application/pdf", "attachment_id": "a1", "size": 1000},
    ]}
    out = Agent._download_pdfs(gmail, msg)
    assert out == [("inv.pdf", b"%PDF-bytes")]
    assert gmail.downloaded == [("m1", "a1")]


def test_download_pdfs_skips_non_pdf_and_oversize():
    gmail = _FakeGmail()
    msg = {"id": "m1", "attachments": [
        {"filename": "pic.png", "mime_type": "image/png", "attachment_id": "a1", "size": 1000},
        {"filename": "big.pdf", "mime_type": "application/pdf", "attachment_id": "a2",
         "size": 20 * 1024 * 1024},
    ]}
    assert Agent._download_pdfs(gmail, msg) == []
    assert gmail.downloaded == []  # nothing downloaded


def test_download_pdfs_no_attachments():
    assert Agent._download_pdfs(_FakeGmail(), {"id": "m1"}) == []


def test_has_pdf():
    assert Agent._has_pdf({"attachments": [{"mime_type": "application/pdf"}]}) is True
    assert Agent._has_pdf({"attachments": [{"mime_type": "image/jpeg"}]}) is False
    assert Agent._has_pdf({"attachments": []}) is False
    assert Agent._has_pdf({}) is False
