from src.documents.tender_intelligence import TenderDocumentIntelligence


class FakeDownload:
    def __init__(self, content: bytes, filename: str):
        self.content = content
        self.filename = filename


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download(self, url: str):
        self.calls.append(url)
        return FakeDownload("Техническое задание: подшипник 6205".encode("utf-8"), "tz.txt")


def test_attachment_urls_are_deduplicated_and_found_recursively():
    raw = {
        "details": {
            "documents": [
                {"url": "https://example.test/a.txt"},
                {"download_url": "https://example.test/a.txt"},
            ]
        },
        "lots": [{"attachments": [{"href": "https://example.test/b.pdf"}]}],
    }
    assert TenderDocumentIntelligence.attachment_urls(raw) == [
        "https://example.test/a.txt",
        "https://example.test/b.pdf",
    ]


def test_adapter_downloads_and_searches_documents_locally():
    downloader = FakeDownloader()
    service = TenderDocumentIntelligence(downloader=downloader)
    result = service.analyze({"attachments": [{"url": "https://example.test/tz.txt"}]}, ["подшипник"])
    assert downloader.calls == ["https://example.test/tz.txt"]
    assert len(result.documents) == 1
    assert len(result.hits) == 1
    assert result.hits[0].keyword == "подшипник"
    assert result.errors == []
