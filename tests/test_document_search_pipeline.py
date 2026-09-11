from src.documents.tender_attachments import TenderAttachmentAnalyzer
from src.documents.downloader import DownloadedDocument
from src.documents.intelligence import DocumentHit, DocumentText
from src.models.tender import Tender
from src.orchestrator import Orchestrator


class FakeDownloader:
    def download(self, url, filename=None):
        return DownloadedDocument(
            filename=filename or "spec.txt",
            content="Подшипники 6205".encode("utf-8"),
            content_type="text/plain",
            source_url=url,
        )


class FakeIntelligence:
    def extract_bytes(self, data, filename):
        return [DocumentText(filename, data.decode("utf-8"), "text/plain")]

    def search(self, documents, keywords):
        return [
            DocumentHit(documents[0].path, keywords[0], "Подшипники 6205", 0, len(keywords[0]))
        ] if keywords else []


def test_document_text_becomes_part_of_tender_full_text():
    tender = Tender(
        platform="test",
        external_id="1",
        title="Закупка оборудования",
        url="https://example.com/tender/1",
        raw_data={"document_search": [{"filename": "spec.txt", "text": "Подшипники 6205"}]},
    )
    assert "Подшипники 6205" in tender.full_text


def test_orchestrator_indexes_attachment_hits():
    service = TenderAttachmentAnalyzer(
        downloader=FakeDownloader(),
        intelligence=FakeIntelligence(),
    )
    orchestrator = Orchestrator.__new__(Orchestrator)
    orchestrator.document_analyzer = service
    tender = Tender(
        platform="test",
        external_id="2",
        title="Закупка оборудования",
        url="https://example.com/tender/2",
        raw_data={"attachments": ["https://example.com/spec.txt"]},
    )

    assert orchestrator._analyze_tender_documents(tender, ["подшипники"])
    assert tender.raw_data["document_search_hits"] == 1
    assert "подшипники" in tender.full_text.casefold()
