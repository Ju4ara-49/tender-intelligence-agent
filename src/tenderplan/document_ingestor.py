"""Download, hash, version, and safely extract tender document text."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from .documents import DocumentExtractionStatus, TenderDocument, TenderDocumentStore, content_sha256


@dataclass(frozen=True, slots=True)
class DocumentIngestResult:
    document: TenderDocument
    downloaded: bool


class TenderDocumentIngestor:
    """Small deterministic document ingestor; unchanged bytes are never re-saved."""

    def __init__(self, store: TenderDocumentStore, timeout: float = 30.0) -> None:
        self.store = store
        self.timeout = timeout

    def ingest(
        self,
        *,
        tender_key: str,
        url: str,
        filename: str = "",
        content_type: str = "",
    ) -> DocumentIngestResult:
        latest = self.store.latest(tender_key, url)
        request = Request(url, headers={"User-Agent": "TenderIntelligenceAgent/1.0"})
        with urlopen(request, timeout=self.timeout) as response:
            content = response.read()
            detected_type = (response.headers.get("Content-Type") or content_type or "").split(";", 1)[0].strip()

        digest = content_sha256(content)
        if latest is not None and latest.sha256 == digest:
            return DocumentIngestResult(document=latest, downloaded=False)

        text, status = self._extract(content, detected_type, url)
        document = self.store.save(
            tender_key=tender_key,
            url=url,
            filename=filename or Path(urlparse(url).path).name,
            content_type=detected_type,
            sha256=digest,
            extraction_status=status,
            extracted_text=text,
        )
        return DocumentIngestResult(document=document, downloaded=True)

    @staticmethod
    def _extract(content: bytes, content_type: str, url: str) -> tuple[str, str]:
        lowered = content_type.lower()
        path = urlparse(url).path.lower()
        if "html" in lowered or path.endswith((".html", ".htm")):
            soup = BeautifulSoup(content, "lxml")
            return soup.get_text(" ", strip=True), DocumentExtractionStatus.EXTRACTED
        if "text/" in lowered or path.endswith((".txt", ".csv", ".xml", ".json")):
            return content.decode("utf-8", errors="replace").strip(), DocumentExtractionStatus.EXTRACTED
        return "", DocumentExtractionStatus.PENDING
