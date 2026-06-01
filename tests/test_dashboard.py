import importlib


def test_invoices_route_renders_invoice(tmp_path, monkeypatch):
    import storage as storage_mod

    db = str(tmp_path / "t.db")
    s = storage_mod.Storage(db)
    s.upsert_invoice(
        invoice_key="4521|b@v.com", message_id="m1", sender_email="b@v.com",
        billed_to="Acme", invoice_name="March consulting", company="Vendor Co",
        invoice_number="4521", amount="$3,200", sent_at=1000,
        payable_at="15 Apr 2026", link="https://pay.example.com/4521",
    )

    monkeypatch.setenv("DB_PATH", db)
    import dashboard.app as appmod
    importlib.reload(appmod)  # re-instantiate storage against the temp DB

    client = appmod.app.test_client()
    resp = client.get("/invoices")
    assert resp.status_code == 200
    assert b"4521" in resp.data
    assert b"Vendor Co" in resp.data


def test_index_and_thread_routes_render(tmp_path, monkeypatch):
    import storage as storage_mod

    db = str(tmp_path / "t.db")
    s = storage_mod.Storage(db)
    s.upsert_thread_summary(
        "Acme Deal", "a@acme.com, legal@acme.com", "<h3>TL;DR</h3> deal moving", "you", 3
    )

    monkeypatch.setenv("DB_PATH", db)
    import dashboard.app as appmod
    importlib.reload(appmod)

    client = appmod.app.test_client()

    index_resp = client.get("/")
    assert index_resp.status_code == 200
    assert b"Acme Deal" in index_resp.data
    assert b"legal@acme.com" in index_resp.data

    detail_resp = client.get("/thread/Acme Deal")
    assert detail_resp.status_code == 200
    assert b"Acme Deal" in detail_resp.data
    assert b"deal moving" in detail_resp.data
