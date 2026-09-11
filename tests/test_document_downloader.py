import pytest

from src.documents.downloader import DocumentDownloadError, DocumentDownloader


def test_downloader_rejects_non_http_urls():
    with pytest.raises(DocumentDownloadError):
        DocumentDownloader._validate_url("file:///etc/passwd")


def test_downloader_rejects_local_and_private_ips():
    for url in ("http://127.0.0.1/file", "http://10.0.0.1/file", "http://localhost/file", "http://[::1]/file"):
        with pytest.raises(DocumentDownloadError):
            DocumentDownloader._validate_url(url)


def test_downloader_accepts_public_http_url():
    DocumentDownloader._validate_url("https://example.com/files/tender.pdf")
