from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from pathlib import Path

import pytest

from src.models.tender import Tender
from src.tenderplan import (
    DocumentExtractionStatus,
    TenderDocumentIngestor,
    TenderDocumentStore,
)
import src.tenderplan.document_ingestor as document_ingestor_module
from src.orchestrator import Orchestrator


class _Page:
    def __init__(self, value: str = ""):
        self.value = value
        self.images = []

    def extract_text(self):
        return self.value


class _ScannedPage:
    def __init__(self):
        self.images = [("page1.png", b"\x89PNG\r\n\x1a\nfakedata")]

    def extract_text(self):
        return ""


class _Reader:
    def __init__(self, _stream):
        self.pages = [_Page("ТЗ на подшипники SKF")]


class _ScannedReader:
    def __init__(self, _stream):
        self.pages = [_ScannedPage()]


def _swap_reader(monkeypatch, reader_cls):
    original = document_ingestor_module.PdfReader
    monkeypatch.setattr(document_ingestor_module, "PdfReader", reader_cls)
    return original


def _ingestor(tmp_path: Path) -> TenderDocumentIngestor:
    store = TenderDocumentStore(tmp_path / "agent.db")
    return TenderDocumentIngestor(store)


def test_pdf_text_layer_is_extracted(monkeypatch, tmp_path):
    """Case: PDF with a real text layer -> EXTRACTED, text preserved, pages
    joined by a real newline (regression for the literal-`\\n` bug)."""
    _swap_reader(monkeypatch, _Reader)
    text, status, diagnostics = _ingestor(tmp_path)._extract(b"pdf", "application/pdf", "spec.pdf")
    assert status == DocumentExtractionStatus.EXTRACTED
    assert "подшипники SKF" in text
    assert "\n" in text or text == "ТЗ на подшипники SKF"
    assert diagnostics == ""


def test_docx_is_extracted(tmp_path):
    """Case: DOCX (office open XML) -> EXTRACTED via zipfile + ElementTree, no
    python-docx dependency required."""
    import zipfile
    from io import BytesIO

    document_xml = (
        '<?xml version="1.0"?>'
        '<document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<body><p><r><t>Требования к подшипникам SKF</t></r></p></body></document>'
    )
    docx = BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    text, status, diagnostics = _ingestor(tmp_path)._extract(
        docx.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "spec.docx",
    )
    assert status == DocumentExtractionStatus.EXTRACTED
    assert "Требования к подшипникам SKF" in text
    assert diagnostics == ""


def test_scanned_pdf_is_unsupported_when_ocr_unavailable(monkeypatch, tmp_path):
    """Case B: a scanned PDF (raster images, no text layer) must NOT be reported
    as `extracted` with an empty string. OCR is unavailable locally, so it must
    be `unsupported` with a diagnostic mentioning OCR — never a fake success."""
    _swap_reader(monkeypatch, _ScannedReader)
    text, status, diagnostics = _ingestor(tmp_path)._extract(b"pdf", "application/pdf", "scan.pdf")
    assert status == DocumentExtractionStatus.UNSUPPORTED
    assert text == ""
    assert "OCR" in diagnostics or "scanned" in diagnostics


def test_ocr_extension_point_returns_none_by_default(tmp_path):
    """The OCR extension point exists and is overridable; in this environment it
    returns None (no OCR engine) so scanned PDFs degrade to `unsupported`."""
    ingestor = _ingestor(tmp_path)
    assert hasattr(ingestor, "_ocr_text")
    assert ingestor._ocr_text(b"bytes", "application/pdf") is None


def test_doc_is_unsupported(tmp_path):
    """DOC (legacy OLE binary) has no safe local extractor -> unsupported."""
    text, status, diagnostics = _ingestor(tmp_path)._extract(
        b"\xd0\xcf\x11\xe0\x00\x00", "application/msword", "old.doc"
    )
    assert status == DocumentExtractionStatus.UNSUPPORTED
    assert text == ""
    assert "DOC" in diagnostics


def test_corrupt_pdf_is_failed(tmp_path):
    """A malformed PDF payload must be `failed` (exception), not crash."""
    text, status, diagnostics = _ingestor(tmp_path)._extract(b"not a real pdf", "application/pdf", "bad.pdf")
    assert status == DocumentExtractionStatus.FAILED
    assert text == ""
    assert diagnostics


def _make_docx(document_xml: str) -> bytes:
    """Build a minimal valid DOCX (zip) payload from raw document.xml text."""
    import zipfile
    from io import BytesIO

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_multiple_documents_extracted_independently(tmp_path):
    """One bad payload must not prevent extraction of a good one: each document
    is processed independently."""
    ingestor = _ingestor(tmp_path)
    document_xml = (
        '<?xml version="1.0"?>'
        '<document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<body><p><r><t>ТТН на подшипники</t></r></p></body></document>'
    )
    good = ingestor._extract(
        _make_docx(document_xml),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "good.docx",
    )
    bad = ingestor._extract(b"\x00\x01", "application/pdf", "bad.pdf")
    assert good[1] == DocumentExtractionStatus.EXTRACTED and "подшипники" in good[0]
    assert bad[1] == DocumentExtractionStatus.FAILED
    # independent: good unaffected by bad
    assert good[0]


class _Handler(BaseHTTPRequestHandler):
    good_body = "<html><body><h1>Техническое задание</h1><p>Подшипники для насоса</p></body></html>"

    def do_GET(self):
        if self.path == "/good.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(self.good_body.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def server_url():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_orchestrator_records_failed_document_and_survives(server_url, tmp_path):
    """One document URL is unreachable (404); the tender must survive, the
    successful document text must land in `document_search_text`, and the
    failed document must be recorded with a diagnostic."""
    store = TenderDocumentStore(tmp_path / "agent.db")
    orch = Orchestrator.__new__(Orchestrator)
    orch.document_ingestor = TenderDocumentIngestor(store)

    tender = Tender(
        platform="eis",
        external_id="100",
        title="Закупка оборудования",
        url=f"{server_url}/missing",
        documents=[
            {"url": f"{server_url}/good.html", "name": "ТЗ.pdf"},
            {"url": f"{server_url}/missing", "name": "absent.pdf"},
        ],
        raw_data={},
    )

    discovered, downloaded, failed = orchestrator_ingest(orch, tender)

    assert discovered == 2
    assert downloaded == 1
    assert failed == 1
    assert tender.raw_data["document_search_text"]
    assert "подшипники" in tender.raw_data["document_search_text"].lower()
    versions = tender.raw_data["document_versions"]
    assert len(versions) == 2
    by_url = {v["url"]: v for v in versions}
    assert by_url[f"{server_url}/good.html"]["extraction_status"] == "extracted"
    assert by_url[f"{server_url}/good.html"]["diagnostics"] == ""
    failed_v = by_url[f"{server_url}/missing"]
    assert failed_v["extraction_status"] == "failed"
    assert failed_v["diagnostics"]  # reason recorded


def orchestrator_ingest(orch, tender):
    return Orchestrator._ingest_tender_documents(orch, tender)


def test_document_text_participates_in_full_text(server_url, tmp_path):
    """Extracted document text must surface in Tender.full_text."""
    store = TenderDocumentStore(tmp_path / "agent.db")
    orch = Orchestrator.__new__(Orchestrator)
    orch.document_ingestor = TenderDocumentIngestor(store)
    tender = Tender(
        platform="eis",
        external_id="7",
        title="Закупка",
        url=f"{server_url}/good.html",
        documents=[{"url": f"{server_url}/good.html", "name": "ТЗ.html"}],
        raw_data={},
    )
    orchestrator_ingest(orch, tender)
    assert "подшипники" in tender.full_text.lower()


def test_document_text_participates_in_keyword_filtering():
    """Keyword filtering runs over Tender.full_text, so document text that
    contains the include keyword makes the tender match even if the title
    alone would not."""
    from src.filters.keyword_filter import KeywordFilter

    flt = KeywordFilter(include=["подшипники"], exclude=[], min_text_length=10)
    with_docs = Tender(
        platform="eis",
        external_id="1",
        title="Закупка оборудования",
        url="https://example.test/1",
        raw_data={"document_search_text": "Требования к подшипники SKF и аналогам"},
    )
    without_docs = Tender(
        platform="eis",
        external_id="2",
        title="Закупка оборудования",
        url="https://example.test/2",
        raw_data={},
    )
    assert flt.matches(with_docs) is True
    assert flt.matches(without_docs) is False
