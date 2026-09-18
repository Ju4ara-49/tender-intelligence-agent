"""Download, hash, version, and safely extract tender document text."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from io import BytesIO
import zipfile
import xml.etree.ElementTree as ET

import openpyxl
from pypdf import PdfReader
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

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
        headers = {"User-Agent": "TenderIntelligenceAgent/1.0"}
        if latest is not None:
            if getattr(latest, "etag", ""):
                headers["If-None-Match"] = latest.etag
            if getattr(latest, "last_modified", ""):
                headers["If-Modified-Since"] = latest.last_modified
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                content = response.read()
                detected_type = (response.headers.get("Content-Type") or content_type or "").split(";", 1)[0].strip()
                etag = response.headers.get("ETag", "")
                last_modified = response.headers.get("Last-Modified", "")
        except HTTPError as exc:
            if exc.code == 304 and latest is not None:
                return DocumentIngestResult(document=latest, downloaded=False)
            raise

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
            etag=etag,
            last_modified=last_modified,
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
        if "pdf" in lowered or path.endswith(".pdf"):
            try:
                reader = PdfReader(BytesIO(content))
                text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
                return text, DocumentExtractionStatus.EXTRACTED
            except Exception:
                return "", DocumentExtractionStatus.FAILED
        if (
            "wordprocessingml" in lowered
            or path.endswith(".docx")
        ):
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    xml = archive.read("word/document.xml")
                root = ET.fromstring(xml)
                text = " ".join(
                    node.text.strip()
                    for node in root.iter()
                    if node.tag.endswith("}t") and node.text and node.text.strip()
                )
                return text, DocumentExtractionStatus.EXTRACTED
            except Exception:
                return "", DocumentExtractionStatus.FAILED
        if (
            "spreadsheetml" in lowered
            or path.endswith(".xlsx")
        ):
            try:
                workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
                parts = []
                for sheet in workbook.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        parts.extend(str(value).strip() for value in row if value is not None and str(value).strip())
                workbook.close()
                return " ".join(parts), DocumentExtractionStatus.EXTRACTED
            except Exception:
                return "", DocumentExtractionStatus.FAILED
        return "", DocumentExtractionStatus.PENDING
