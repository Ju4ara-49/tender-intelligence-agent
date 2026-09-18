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
