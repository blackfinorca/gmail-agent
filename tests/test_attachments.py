import attachments


def test_uses_pdfplumber_text_when_present(monkeypatch):
    calls = {"ocr": 0}
    monkeypatch.setattr(attachments, "_pdfplumber_text", lambda d: "INVOICE Total 500,000 JPY due 2026")
    monkeypatch.setattr(attachments, "_ocr_text", lambda d: calls.__setitem__("ocr", calls["ocr"] + 1) or "OCR")
    out = attachments.pdf_to_text(b"%PDF-fake")
    assert "500,000" in out
    assert calls["ocr"] == 0  # OCR not needed


def test_falls_back_to_ocr_for_scanned_pdf(monkeypatch):
    monkeypatch.setattr(attachments, "_pdfplumber_text", lambda d: "   ")  # scan -> no text
    monkeypatch.setattr(attachments, "_ocr_text", lambda d: "OHARA & FURUKAWA Total Amount Due 500,000 JPY")
    out = attachments.pdf_to_text(b"%PDF-scan")
    assert "OHARA" in out


def test_returns_empty_when_both_fail(monkeypatch):
    def boom(d):
        raise RuntimeError("no binary")
    monkeypatch.setattr(attachments, "_pdfplumber_text", boom)
    monkeypatch.setattr(attachments, "_ocr_text", boom)
    assert attachments.pdf_to_text(b"%PDF") == ""


def test_short_text_triggers_ocr(monkeypatch):
    # pdfplumber yields a few chars (< MIN_TEXT_CHARS) -> OCR is tried
    monkeypatch.setattr(attachments, "_pdfplumber_text", lambda d: "hi")
    monkeypatch.setattr(attachments, "_ocr_text", lambda d: "a much longer OCR result with the invoice total")
    out = attachments.pdf_to_text(b"%PDF")
    assert "OCR result" in out
