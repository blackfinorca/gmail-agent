from email.utils import parsedate_to_datetime

from agent import Agent


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
