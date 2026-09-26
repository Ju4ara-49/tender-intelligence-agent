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

    DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
    DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
    DEFAULT_MAX_EXTRACTED_TEXT_BYTES = 10 * 1024 * 1024

    def __init__(
        self,
        store: TenderDocumentStore,
        timeout: float = 30.0,
        *,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
        max_archive_uncompressed_bytes: int = DEFAULT_MAX_ARCHIVE_UNCOMPRESSED_BYTES,
        max_extracted_text_bytes: int = DEFAULT_MAX_EXTRACTED_TEXT_BYTES,
    ) -> None:
        self.store = store
        self.timeout = timeout
        self.max_download_bytes = int(max_download_bytes)
        self.max_archive_uncompressed_bytes = int(max_archive_uncompressed_bytes)
        self.max_extracted_text_bytes = int(max_extracted_text_bytes)
        if min(self.max_download_bytes, self.max_archive_uncompressed_bytes, self.max_extracted_text_bytes) <= 0:
            raise ValueError("document ingestion limits must be positive")

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
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > self.max_download_bytes:
                    raise ValueError(f"document exceeds download limit ({self.max_download_bytes} bytes)")
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = response.read(min(1024 * 1024, self.max_download_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        raise ValueError(f"document exceeds download limit ({self.max_download_bytes} bytes)")
                    chunks.append(chunk)
                content = b"".join(chunks)
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

        text, status, diagnostics = self._extract(content, detected_type, url)
        document = self.store.save(
            tender_key=tender_key,
            url=url,
            filename=filename or Path(urlparse(url).path).name,
            content_type=detected_type,
            sha256=digest,
            extraction_status=status,
            extracted_text=text,
            diagnostics=diagnostics,
            etag=etag,
            last_modified=last_modified,
        )
        return DocumentIngestResult(document=document, downloaded=True)

    def _ocr_text(self, content: bytes, content_type: str) -> str | None:
        """OCR для сканированных PDF. Архитектурная точка расширения.

        В окружении без локального OCR-движка (pytesseract + tesseract или аналог)
        возвращает ``None``: для сканированного PDF это даёт статус
        ``unsupported`` с диагностикой, а не подмена пустого результата на
        ``extracted``. Для реального OCR подкласс переопределяет метод и
        возвращает извлечённый текст.
        """
        return None

    def _bounded_text(self, text: str) -> str:
        raw = text.encode("utf-8", errors="replace")
        if len(raw) <= self.max_extracted_text_bytes:
            return text
        return raw[:self.max_extracted_text_bytes].decode("utf-8", errors="ignore")

    def _extract(self, content: bytes, content_type: str, url: str) -> tuple[str, str, str]:
        lowered = content_type.lower()
        path = urlparse(url).path.lower()
        if "html" in lowered or path.endswith((".html", ".htm")):
            soup = BeautifulSoup(content, "lxml")
            return self._bounded_text(soup.get_text(" ", strip=True)), DocumentExtractionStatus.EXTRACTED, ""
        if "text/" in lowered or path.endswith((".txt", ".csv", ".xml", ".json")):
            return self._bounded_text(content.decode("utf-8", errors="replace").strip()), DocumentExtractionStatus.EXTRACTED, ""
        if "pdf" in lowered or path.endswith(".pdf"):
            try:
                reader = PdfReader(BytesIO(content))
                pages = list(reader.pages)
                text = "\n".join(page.extract_text() or "" for page in pages).strip()
                if not text:
                    scanned = False
                    try:
                        scanned = any(page.images for page in pages)
                    except Exception:
                        scanned = False
                    if scanned:
                        ocr = self._ocr_text(content, content_type)
                        if ocr:
                            return ocr.strip(), DocumentExtractionStatus.EXTRACTED, ""
                        return "", DocumentExtractionStatus.UNSUPPORTED, "scanned PDF: no text layer (raster images); OCR engine unavailable"
                return self._bounded_text(text), DocumentExtractionStatus.EXTRACTED, ""
            except Exception as exc:
                return "", DocumentExtractionStatus.FAILED, f"pdf extraction failed: {type(exc).__name__}: {exc}"
        if "wordprocessingml" in lowered or path.endswith(".docx"):
            try:
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    info = archive.getinfo("word/document.xml")
                    if info.file_size > self.max_archive_uncompressed_bytes:
                        return "", DocumentExtractionStatus.FAILED, "docx XML exceeds archive extraction limit"
                    xml = archive.read("word/document.xml")
                root = ET.fromstring(xml)
                text = " ".join(
                    node.text.strip()
                    for node in root.iter()
                    if node.tag.endswith("}t") and node.text and node.text.strip()
                )
                return text, DocumentExtractionStatus.EXTRACTED, ""
            except Exception as exc:
                return "", DocumentExtractionStatus.FAILED, f"docx extraction failed: {type(exc).__name__}: {exc}"
        if "msword" in lowered or (path.endswith(".doc") and not path.endswith(".docx")):
            return "", DocumentExtractionStatus.UNSUPPORTED, "DOC/OLE binary format not supported; requires an external converter"
        if "spreadsheetml" in lowered or path.endswith(".xlsx"):
            try:
                workbook = openpyxl.load_workbook(BytesIO(content), read_only=True, data_only=True)
                parts = []
                for sheet in workbook.worksheets:
                    for row in sheet.iter_rows(values_only=True):
                        parts.extend(str(value).strip() for value in row if value is not None and str(value).strip())
                workbook.close()
                return " ".join(parts), DocumentExtractionStatus.EXTRACTED, ""
            except Exception as exc:
                return "", DocumentExtractionStatus.FAILED, f"xlsx extraction failed: {type(exc).__name__}: {exc}"
        return "", DocumentExtractionStatus.PENDING, "unrecognized content type; no extractor matched"
