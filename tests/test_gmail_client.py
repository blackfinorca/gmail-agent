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


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _FakeService:
    """Minimal stand-in for the Gmail API service chain."""

    def __init__(self, ids):
        self._ids = ids
        self.got = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.last_list_kwargs = kwargs
        return _Exec({"messages": [{"id": i} for i in self._ids]})

    def get(self, userId, id, format):
        self.got.append(id)
        return _Exec({"id": id, "threadId": "t", "payload": {"headers": []}, "snippet": ""})


def test_fetch_new_messages_skips_processed_ids():
    client = GmailClient()
    svc = _FakeService(["a", "b", "c"])
    client.service = svc
    out = client.fetch_new_messages(0, skip_ids={"b"})
    fetched = {m["id"] for m in out}
    assert fetched == {"a", "c"}        # 'b' skipped, not returned
    assert "b" not in svc.got           # and never downloaded


def test_fetch_new_messages_no_skip_fetches_all():
    client = GmailClient()
    svc = _FakeService(["a", "b"])
    client.service = svc
    out = client.fetch_new_messages(0)
    assert {m["id"] for m in out} == {"a", "b"}
    assert set(svc.got) == {"a", "b"}


def test_fetch_new_messages_builds_query():
    client = GmailClient()
    svc = _FakeService(["a"])
    client.service = svc
    client.fetch_new_messages(0, query_filter='subject:"SPA" OR from:x@y.com')
    # since=0 -> no after: clause, just the parenthesised filter
    assert svc.last_list_kwargs["q"] == '(subject:"SPA" OR from:x@y.com)'


def test_fetch_new_messages_combines_since_and_filter():
    client = GmailClient()
    svc = _FakeService(["a"])
    client.service = svc
    client.fetch_new_messages(1700000000, query_filter="from:x@y.com")
    assert svc.last_list_kwargs["q"] == "after:1700000000 (from:x@y.com)"


def test_fetch_new_messages_no_query_when_no_filter_and_all():
    client = GmailClient()
    svc = _FakeService(["a"])
    client.service = svc
    client.fetch_new_messages(0)
    assert "q" not in svc.last_list_kwargs  # whole mailbox, no filter
