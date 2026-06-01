from gmail_client import GmailClient


def test_collect_attachments_walks_mime_tree():
    payload = {
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"data": ""}},
            {"mimeType": "application/pdf", "filename": "invoice.pdf",
             "body": {"attachmentId": "att-1", "size": 1234}},
            {"mimeType": "multipart/mixed", "filename": "", "parts": [
                {"mimeType": "application/pdf", "filename": "nested.pdf",
                 "body": {"attachmentId": "att-2", "size": 99}},
            ]},
        ]
    }
    atts = GmailClient()._collect_attachments(payload)
    assert len(atts) == 2
    assert atts[0] == {"filename": "invoice.pdf", "mime_type": "application/pdf",
                       "attachment_id": "att-1", "size": 1234}
    assert atts[1]["filename"] == "nested.pdf"
    assert atts[1]["attachment_id"] == "att-2"


def test_collect_attachments_empty_when_no_parts():
    assert GmailClient()._collect_attachments({}) == []
