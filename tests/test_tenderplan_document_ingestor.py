from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

from src.tenderplan import TenderDocumentStore, TenderDocumentIngestor


class Handler(BaseHTTPRequestHandler):
    payload = b"<html><body><h1>Technical specification</h1><p>Bearings</p></body></html>"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/spec.html"
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_ingestor_downloads_hashes_and_extracts_html(tmp_path: Path, server: str):
    store = TenderDocumentStore(tmp_path / "agent.db")
    ingestor = TenderDocumentIngestor(store)

    result = ingestor.ingest(tender_key="eis:1", url=server)

    assert result.downloaded is True
    assert result.document.version == 1
    assert result.document.extraction_status == "extracted"
    assert "Technical specification" in result.document.extracted_text
    assert "Bearings" in result.document.extracted_text


def test_ingestor_does_not_create_duplicate_version_for_unchanged_content(
    tmp_path: Path, server: str
):
    store = TenderDocumentStore(tmp_path / "agent.db")
    ingestor = TenderDocumentIngestor(store)

    first = ingestor.ingest(tender_key="eis:1", url=server)
    second = ingestor.ingest(tender_key="eis:1", url=server)

    assert first.downloaded is True
    assert second.downloaded is False
    assert second.document.document_id == first.document.document_id
    assert len(store.list_for_tender("eis:1")) == 1


def test_ingestor_uses_conditional_request_for_unchanged_document(tmp_path: Path):
    class ConditionalHandler(BaseHTTPRequestHandler):
        requests = 0
        payload = b"stable document"
        etag = '"stable-v1"'

        def do_GET(self):
            type(self).requests += 1
            if self.headers.get("If-None-Match") == self.etag:
                self.send_response(304)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("ETag", self.etag)
            self.end_headers()
            self.wfile.write(self.payload)

        def log_message(self, format, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), ConditionalHandler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{httpd.server_port}/spec.txt"
        store = TenderDocumentStore(tmp_path / "conditional.db")
        ingestor = TenderDocumentIngestor(store)

        first = ingestor.ingest(tender_key="eis:conditional", url=url)
        second = ingestor.ingest(tender_key="eis:conditional", url=url)

        assert first.downloaded is True
        assert second.downloaded is False
        assert second.document.document_id == first.document.document_id
        assert second.document.etag == '"stable-v1"'
        assert ConditionalHandler.requests == 2
        assert len(store.list_for_tender("eis:conditional")) == 1
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_ingestor_rejects_download_above_configured_limit(tmp_path: Path):
    class LargeHandler(BaseHTTPRequestHandler):
        payload = b"x" * 64

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(self.payload)))
            self.end_headers()
            self.wfile.write(self.payload)

        def log_message(self, format, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), LargeHandler)
    thread = Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        store = TenderDocumentStore(tmp_path / "limit.db")
        ingestor = TenderDocumentIngestor(store, max_download_bytes=32)
        with pytest.raises(ValueError, match="download limit"):
            ingestor.ingest(tender_key="eis:large", url=f"http://127.0.0.1:{httpd.server_port}/large.txt")
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def test_ingestor_bounds_extracted_text(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "text-limit.db")
    ingestor = TenderDocumentIngestor(store, max_extracted_text_bytes=20)
    text, status, _ = ingestor._extract(b"abcdefghijklmnopqrstuvwxyz", "text/plain", "http://example.test/a.txt")
    assert status == "extracted"
    assert len(text.encode("utf-8")) <= 20


def test_ingestor_rejects_oversized_docx_xml(tmp_path: Path):
    import zipfile
    from io import BytesIO

    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("word/document.xml", "<w:document>" + ("x" * 100) + "</w:document>")

    store = TenderDocumentStore(tmp_path / "docx-limit.db")
    ingestor = TenderDocumentIngestor(store, max_archive_uncompressed_bytes=32)
    text, status, diagnostics = ingestor._extract(payload.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "http://example.test/a.docx")
    assert text == ""
    assert status == "failed"
    assert "archive extraction limit" in diagnostics


def test_ingestor_bounds_xlsx_extraction(tmp_path: Path):
    from io import BytesIO
    import openpyxl

    payload = BytesIO()
    workbook = openpyxl.Workbook()
    workbook.active["A1"] = "x" * 100
    workbook.save(payload)
    workbook.close()

    store = TenderDocumentStore(tmp_path / "xlsx-limit.db")
    ingestor = TenderDocumentIngestor(store, max_extracted_text_bytes=20)
    text, status, diagnostics = ingestor._extract(
        payload.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "http://example.test/a.xlsx",
    )
    assert len(text.encode("utf-8")) <= 20
    assert status == "partial"
    assert "truncated" in diagnostics


def test_ingestor_rejects_docx_archive_with_large_total_uncompressed_size(tmp_path: Path):
    from io import BytesIO
    import zipfile

    payload = BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("word/document.xml", "<w:document><w:t>ok</w:t></w:document>")
        archive.writestr("word/large.bin", b"x" * 100)

    store = TenderDocumentStore(tmp_path / "docx-total-limit.db")
    ingestor = TenderDocumentIngestor(store, max_archive_uncompressed_bytes=64)
    text, status, diagnostics = ingestor._extract(
        payload.getvalue(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "http://example.test/a.docx",
    )
    assert text == ""
    assert status == "failed"
    assert "archive exceeds extraction limit" in diagnostics
