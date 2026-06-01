from storage import Storage


def _invoice_kwargs(**overrides):
    base = dict(
        invoice_key="4521|billing@v.com",
        message_id="m1",
        sender_email="billing@v.com",
        invoice_group="Accounting",
        billed_to="Acme",
        invoice_name="March consulting",
        company="Vendor Co",
        invoice_number="4521",
        amount="$3,200",
        sent_at=1000,
        payable_at="15 Apr 2026",
        link="http://x",
    )
    base.update(overrides)
    return base


def test_upsert_invoice_and_get(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs())
    rows = s.get_all_invoices()
    assert len(rows) == 1
    assert rows[0]["invoice_number"] == "4521"
    assert rows[0]["amount"] == "$3,200"
    assert rows[0]["invoice_group"] == "Accounting"


def test_get_all_invoices_grouped(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="a", invoice_group="Benten"))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="b", invoice_group="Benten"))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="c", invoice_group="Moby"))
    grouped = s.get_all_invoices_grouped()
    assert set(grouped) == {"Benten", "Moby"}
    assert len(grouped["Benten"]) == 2
    assert len(grouped["Moby"]) == 1


def test_upsert_invoice_dedupes_on_key(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs(amount="$100"))
    s.upsert_invoice(**_invoice_kwargs(amount="$200"))
    rows = s.get_all_invoices()
    assert len(rows) == 1
    assert rows[0]["amount"] == "$200"


def test_get_all_invoices_orders_by_sent_at_desc(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="a", sent_at=100))
    s.upsert_invoice(**_invoice_kwargs(invoice_key="b", sent_at=200))
    rows = s.get_all_invoices()
    assert [r["invoice_key"] for r in rows] == ["b", "a"]


def test_upsert_thread_summary_and_get(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_thread_summary("Acme Deal", "a@x.com, b@x.com", "<h3>TL;DR</h3>", "you", 2)
    row = s.get_thread_summary("Acme Deal")
    assert row["members"] == "a@x.com, b@x.com"
    assert row["message_count"] == 2
    assert row["pending_action"] == "you"


def test_upsert_thread_summary_accumulates_count(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_thread_summary("Acme Deal", "a@x.com", "s1", "none", 2)
    s.upsert_thread_summary("Acme Deal", "a@x.com", "s2", "them", 3)
    row = s.get_thread_summary("Acme Deal")
    assert row["message_count"] == 5
    assert row["summary"] == "s2"
    assert row["pending_action"] == "them"


def test_get_all_thread_summaries(tmp_path):
    s = Storage(str(tmp_path / "t.db"))
    s.upsert_thread_summary("One", "a@x.com", "s", "none", 1)
    s.upsert_thread_summary("Two", "b@x.com", "s", "none", 1)
    names = {r["thread_name"] for r in s.get_all_thread_summaries()}
    assert names == {"One", "Two"}
