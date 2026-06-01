from storage import Storage


def _invoice_kwargs(**overrides):
    base = dict(
        invoice_key="4521|billing@v.com",
        message_id="m1",
        sender_email="billing@v.com",
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
