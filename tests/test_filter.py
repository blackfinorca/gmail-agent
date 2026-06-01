from config import FilterRules
from filter_engine import FilterEngine


def make(thread, inv):
    return FilterEngine(FilterRules(thread_list=thread, invoice_senders=inv))


def test_matches_thread():
    e = make(["info@track"], [])
    assert e.matches_thread({"sender": "Info <info@trackrecord.com>", "subject": "", "body_text": ""}) is True
    assert e.matches_thread({"sender": "x@other.com", "subject": "", "body_text": ""}) is False


def test_matches_invoice():
    e = make([], ["billing@stripe.com"])
    assert e.matches_invoice({"sender": "Stripe <billing@stripe.com>", "subject": "", "body_text": ""}) is True
    assert e.matches_invoice({"sender": "x@other.com", "subject": "", "body_text": ""}) is False


def test_classify_thread():
    e = make(["info@track"], [])
    assert e.classify({"sender": "info@trackrecord.com", "subject": "", "body_text": ""}) == "sender:info@track"


def test_classify_unmatched():
    e = make(["info@track"], [])
    assert e.classify({"sender": "x@other.com", "subject": "", "body_text": ""}) == "unmatched"
