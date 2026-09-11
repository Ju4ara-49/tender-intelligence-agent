from src.documents.tender_attachments import TenderAttachmentAnalyzer
from src.documents.downloader import DownloadedDocument
from src.documents.intelligence import DocumentHit, DocumentText


class FakeDownloader:
    def download(self, url, filename=None):
        return DownloadedDocument(
            filename=filename or "notice.txt",
            content="Закупаем подшипники".encode("utf-8"),
            content_type="text/plain",
            source_url=url,
        )


class FakeIntelligence:
    def extract_bytes(self, data, filename):
        return [DocumentText(filename, data.decode("utf-8"), "text/plain")]

    def search(self, documents, keywords):
        return [
            DocumentHit(documents[0].path, keywords[0], keywords[0], 10, 10 + len(keywords[0]))
        ] if keywords else []


def test_discover_finds_nested_http_links_and_deduplicates():
    raw = {
        "details": {
            "attachments": [
                {"url": "https://example.com/docs/spec.pdf"},
                {"url": "https://example.com/docs/spec.pdf"},
                "https://example.com/docs/requirements.docx",
                "not-a-url",
            ]
        }
    }
    result = TenderAttachmentAnalyzer.discover(raw)
    assert [item.url for item in result] == [
        "https://example.com/docs/spec.pdf",
        "https://example.com/docs/requirements.docx",
    ]
    assert result[0].filename == "spec.pdf"


def test_discover_ignores_non_http_schemes():
    raw = {"a": ["file:///tmp/secret.pdf", "javascript:alert(1)", "ftp://example.com/a.pdf"]}
    assert TenderAttachmentAnalyzer.discover(raw) == []


def test_analyze_downloads_and_searches_locally():
    service = TenderAttachmentAnalyzer(
        downloader=FakeDownloader(),
        intelligence=FakeIntelligence(),
    )
    result = service.analyze({"attachment": "https://example.com/notice.txt"}, ["подшипники"])
    assert len(result) == 1
    assert result[0].downloaded.source_url == "https://example.com/notice.txt"
    assert result[0].documents[0].text == "Закупаем подшипники"
    assert result[0].hits[0].keyword == "подшипники"


def test_attachment_limit_is_enforced():
    raw = {"urls": [f"https://example.com/{index}.txt" for index in range(10)]}
    result = TenderAttachmentAnalyzer.discover(raw, max_attachments=3)
    assert len(result) == 3
