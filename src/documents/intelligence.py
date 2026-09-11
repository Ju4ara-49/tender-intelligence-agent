"""Безопасное извлечение текста из документов тендера без облачного AI."""
from __future__ import annotations

import codecs
import html
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from openpyxl import load_workbook

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


MAX_ARCHIVE_FILES = 500
MAX_ARCHIVE_UNCOMPRESSED = 200 * 1024 * 1024
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 500
MAX_NESTING_DEPTH = 3
SUPPORTED_TEXT_EXTENSIONS = {".txt", ".csv", ".xml", ".html", ".htm", ".json"}
SUPPORTED_OFFICE_EXTENSIONS = {".docx", ".xlsx", ".xlsm"}
SUPPORTED_ARCHIVES = {".zip"}
SUPPORTED_PDF = {".pdf"}


@dataclass(frozen=True)
class DocumentText:
    path: str
    text: str
    mime_hint: str = ""


@dataclass(frozen=True)
class DocumentHit:
    path: str
    keyword: str
    snippet: str
    start: int
    end: int


class UnsafeArchiveError(ValueError):
    """Архив содержит опасный путь или превышает лимиты."""


class DocumentIntelligence:
    """Извлечение, нормализация и локальный поиск по документам и архивам."""

    def __init__(self, max_file_bytes: int = MAX_FILE_BYTES, max_archive_files: int = MAX_ARCHIVE_FILES,
                 max_archive_uncompressed: int = MAX_ARCHIVE_UNCOMPRESSED, max_pdf_pages: int = MAX_PDF_PAGES,
                 max_nesting_depth: int = MAX_NESTING_DEPTH) -> None:
        self.max_file_bytes = max_file_bytes
        self.max_archive_files = max_archive_files
        self.max_archive_uncompressed = max_archive_uncompressed
        self.max_pdf_pages = max_pdf_pages
        self.max_nesting_depth = max_nesting_depth

    @staticmethod
    def normalize(text: str) -> str:
        text = html.unescape(text or "")
        text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = text.replace("\x00", " ")
        text = re.sub(r"[\t\r ]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _decode_text(data: bytes) -> str:
        if data.startswith(codecs.BOM_UTF8):
            return data.decode("utf-8-sig")
        for encoding in ("utf-8", "cp1251", "koi8-r"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    def extract_file(self, path: Path, virtual_path: str | None = None) -> list[DocumentText]:
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size > self.max_file_bytes:
            raise ValueError(f"Файл слишком большой: {path}")
        return self._extract_bytes(path.read_bytes(), virtual_path or path.name, path.suffix.lower(), 0)

    def extract_bytes(self, data: bytes, filename: str) -> list[DocumentText]:
        if len(data) > self.max_file_bytes:
            raise ValueError(f"Файл слишком большой: {filename}")
        return self._extract_bytes(data, filename, Path(filename).suffix.lower(), 0)

    def _extract_bytes(self, data: bytes, name: str, ext: str, depth: int) -> list[DocumentText]:
        if len(data) > self.max_file_bytes:
            raise ValueError(f"Файл слишком большой: {name}")
        if ext in SUPPORTED_TEXT_EXTENSIONS:
            text = self._decode_text(data)
            try:
                if ext == ".xml":
                    root = ElementTree.fromstring(data)
                    text = " ".join(part.strip() for part in root.itertext() if part and part.strip())
                elif ext == ".json":
                    text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
            except (ElementTree.ParseError, ValueError, UnicodeError, json.JSONDecodeError):
                pass
            return [DocumentText(name, self.normalize(text), ext)]
        if ext in SUPPORTED_PDF:
            return [DocumentText(name, self._pdf(data), "application/pdf")]
        if ext in SUPPORTED_OFFICE_EXTENSIONS:
            self._validate_zip_container(data, name)
            if ext in {".xlsx", ".xlsm"}:
                return [DocumentText(name, self._xlsx(data), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]
            return [DocumentText(name, self._docx(data), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")]
        if ext in SUPPORTED_ARCHIVES:
            return self._extract_archive(data, name, depth)
        return []

    def _pdf(self, data: bytes) -> str:
        if PdfReader is None:
            raise RuntimeError("Для PDF нужен пакет pypdf")
        reader = PdfReader(io.BytesIO(data), strict=False)
        if len(reader.pages) > self.max_pdf_pages:
            raise ValueError("PDF содержит слишком много страниц")
        return self.normalize("\n\n".join(page.extract_text() or "" for page in reader.pages))

    def _docx(self, data: bytes) -> str:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                xml = archive.read("word/document.xml")
            except KeyError:
                return ""
        root = ElementTree.fromstring(xml)
        texts: list[str] = []
        for node in root.iter():
            if node.tag.endswith("}t") and node.text:
                texts.append(node.text)
            elif node.tag.endswith("}tab"):
                texts.append("\t")
            elif node.tag.endswith("}br") or node.tag.endswith("}p"):
                texts.append("\n")
        return self.normalize("".join(texts))

    def _xlsx(self, data: bytes) -> str:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines: list[str] = []
        try:
            for sheet in workbook.worksheets:
                lines.append(f"[Лист: {sheet.title}]")
                for row in sheet.iter_rows(values_only=True):
                    values = [str(value).strip() for value in row if value is not None and str(value).strip()]
                    if values:
                        lines.append(" | ".join(values))
        finally:
            workbook.close()
        return self.normalize("\n".join(lines))

    @staticmethod
    def _validate_zip_container(data: bytes, name: str) -> None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = [item for item in archive.infolist() if not item.is_dir()]
                if len(infos) > MAX_ARCHIVE_FILES or sum(item.file_size for item in infos) > MAX_ARCHIVE_UNCOMPRESSED:
                    raise UnsafeArchiveError(f"ZIP-контейнер {name} превышает безопасные лимиты")
                for info in infos:
                    DocumentIntelligence._validate_archive_member(info.filename)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"Повреждённый ZIP-контейнер: {name}") from exc

    def _extract_archive(self, data: bytes, name: str, depth: int) -> list[DocumentText]:
        if depth >= self.max_nesting_depth:
            raise UnsafeArchiveError("Превышена максимальная глубина вложенных архивов")
        results: list[DocumentText] = []
        total = 0
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                infos = [info for info in archive.infolist() if not info.is_dir()]
                if len(infos) > self.max_archive_files:
                    raise UnsafeArchiveError("Архив содержит слишком много файлов")
                for info in infos:
                    self._validate_archive_member(info.filename)
                    total += info.file_size
                    if total > self.max_archive_uncompressed:
                        raise UnsafeArchiveError("Распакованный размер архива превышает лимит")
                    member = archive.read(info)
                    if len(member) > self.max_file_bytes:
                        continue
                    virtual = f"{name}!/{info.filename}"
                    try:
                        results.extend(self._extract_bytes(member, virtual, Path(info.filename).suffix.lower(), depth + 1))
                    except UnsafeArchiveError:
                        raise
                    except (ValueError, zipfile.BadZipFile, UnicodeError):
                        continue
        except zipfile.BadZipFile as exc:
            raise ValueError(f"Повреждённый ZIP-архив: {name}") from exc
        return results

    @staticmethod
    def _validate_archive_member(name: str) -> None:
        normalized = name.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
            raise UnsafeArchiveError(f"Опасный путь в архиве: {name}")

    def search(self, documents: list[DocumentText], keywords: list[str], context: int = 100) -> list[DocumentHit]:
        hits: list[DocumentHit] = []
        context = max(0, int(context))
        for document in documents:
            text_lower = document.text.casefold()
            for keyword in keywords:
                needle = str(keyword).strip()
                if not needle:
                    continue
                start = 0
                needle_lower = needle.casefold()
                while True:
                    position = text_lower.find(needle_lower, start)
                    if position < 0:
                        break
                    left = max(0, position - context)
                    right = min(len(document.text), position + len(needle) + context)
                    snippet = document.text[left:right].replace("\n", " ").strip()
                    hits.append(DocumentHit(document.path, needle, snippet, position, position + len(needle)))
                    start = position + max(1, len(needle))
                    if len(hits) >= 500:
                        return hits
        return hits

    def analyze_paths(self, paths: list[Path], keywords: list[str]) -> tuple[list[DocumentText], list[DocumentHit]]:
        documents: list[DocumentText] = []
        for path in paths:
            documents.extend(self.extract_file(Path(path)))
        return documents, self.search(documents, keywords)
