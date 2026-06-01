from config import FilterRules
from filter_engine import FilterEngine


def make(thread, inv):
    return FilterEngine(FilterRules(thread_list=thread, invoice_groups=inv))


def test_thread_for_matches_subject_keyword():
    e = make({"Draft SPA": ["SPA", "share purchase"]}, {})
    assert e.thread_for({"subject": "Re: Draft SPA v3", "sender": "anyone@x.com"}) == "Draft SPA"
    assert e.thread_for({"subject": "the share purchase terms", "sender": "x@y.com"}) == "Draft SPA"


def test_thread_for_ignores_sender():
    e = make({"Draft SPA": ["SPA"]}, {})
    # keyword is in the sender but NOT the subject -> no match (subject-only)
    assert e.thread_for({"subject": "hello", "sender": "spa@firm.com"}) is None


def test_thread_for_none_when_unmatched():
    e = make({"Draft SPA": ["SPA"]}, {})
    assert e.thread_for({"subject": "lunch?", "sender": "x@y.com"}) is None


def test_thread_for_first_match_wins():
    e = make({"First": ["deal"], "Second": ["deal"]}, {})
    assert e.thread_for({"subject": "the deal", "sender": "x@y.com"}) == "First"


def test_invoice_group_for_matches_sender():
    e = make({}, {"Accounting": ["billing@stripe.com"]})
    assert e.invoice_group_for({"sender": "Stripe <billing@stripe.com>"}) == "Accounting"
    assert e.invoice_group_for({"sender": "x@other.com"}) is None


def test_gmail_query_combines_subjects_and_senders():
    e = make({"Draft SPA": ["SPA", "share purchase"]}, {"Law": ["lawyer@firm.jp"]})
    q = e.gmail_query()
    assert 'subject:"SPA"' in q
    assert 'subject:"share purchase"' in q
    # invoice-sender clause requires a PDF attachment
    assert "from:lawyer@firm.jp has:attachment filename:pdf" in q
    assert " OR " in q


def test_gmail_query_empty_when_no_rules():
    assert make({}, {}).gmail_query() == ""
