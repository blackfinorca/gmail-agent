from config import FilterRules
from filter_engine import FilterEngine


def make(thread, inv):
    return FilterEngine(FilterRules(thread_list=thread, invoice_senders=inv))


def test_thread_for_returns_group_name():
    e = make({"Acme Deal": ["info@track", "legal@acme"]}, [])
    assert e.thread_for({"sender": "Info <info@trackrecord.com>"}) == "Acme Deal"
    assert e.thread_for({"sender": "Legal <legal@acme.com>"}) == "Acme Deal"


def test_thread_for_none_when_unmatched():
    e = make({"Acme Deal": ["info@track"]}, [])
    assert e.thread_for({"sender": "x@other.com"}) is None


def test_thread_for_first_match_wins():
    e = make({"First": ["shared@x.com"], "Second": ["shared@x.com"]}, [])
    assert e.thread_for({"sender": "shared@x.com"}) == "First"


def test_matches_invoice():
    e = make({}, ["billing@stripe.com"])
    assert e.matches_invoice({"sender": "Stripe <billing@stripe.com>"}) is True
    assert e.matches_invoice({"sender": "x@other.com"}) is False
