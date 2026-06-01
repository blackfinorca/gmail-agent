"""PDF text extraction for invoice attachments.

Tries fast digital-text extraction first (pdfplumber); if the PDF carries
little or no extractable text — i.e. it's a scan — falls back to OCR
(pdf2image + Tesseract). All heavy imports are lazy so this module loads even
when the optional libraries / system binaries are absent; failures degrade to
an empty string rather than raising.

OCR requires the `tesseract` and `poppler` system binaries to be installed.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

# Below this many non-whitespace chars, treat the PDF as scanned and try OCR.
MIN_TEXT_CHARS = 20


def _pdfplumber_text(data: bytes) -> str:
    import pdfplumber

    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _ocr_text(data: bytes) -> str:
    from pdf2image import convert_from_bytes
    import pytesseract

    images = convert_from_bytes(data)
    return "\n".join(pytesseract.image_to_string(img) for img in images)


def pdf_to_text(data: bytes) -> str:
    """Extract text from a PDF. Digital text first, OCR fallback for scans.

    Never raises — returns the best text it can, or '' on total failure.
    """
    text = ""
    try:
        text = _pdfplumber_text(data)
    except Exception as e:
        logger.warning("pdfplumber failed, will try OCR: %s", e)

    if len(text.strip()) >= MIN_TEXT_CHARS:
        return text.strip()

    try:
        ocr = _ocr_text(data)
        if ocr.strip():
            return ocr.strip()
    except Exception as e:
        logger.warning("OCR fallback failed (is tesseract/poppler installed?): %s", e)

    return text.strip()
