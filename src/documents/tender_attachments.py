"""Адаптер вложений тендера -> локальный Document Intelligence.

Коллекторы проекта пока не имеют единого attachment API, поэтому этот слой
работает поверх raw_data и не зависит от конкретной площадки. Он только
извлекает HTTP(S)-ссылки из структурированных данных; загрузка проходит через
SSRF-защищённый DocumentDownloader, а анализ — полностью локально.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.documents.downloader import DocumentDownloader, DownloadedDocument
from src.documents.intelligence import DocumentHit, DocumentIntelligence, DocumentText


@dataclass(frozen=True)
class TenderAttachment:
    url: str
    filename: str | None = None
    content_type: str = ""


@dataclass(frozen=True)
class TenderAttachmentAnalysis:
    attachment: TenderAttachment
    downloaded: DownloadedDocument
    documents: tuple[DocumentText, ...]
    hits: tuple[DocumentHit, ...]


class TenderAttachmentAnalyzer:
    """Находит и локально анализирует вложения из raw_data тендера."""

    def __init__(
        self,
        downloader: DocumentDownloader | None = None,
        intelligence: DocumentIntelligence | None = None,
        max_attachments: int = 30,
    ) -> None:
        if max_attachments <= 0:
            raise ValueError("max_attachments должен быть положительным")
        self.downloader = downloader or DocumentDownloader()
        self.intelligence = intelligence or DocumentIntelligence()
        self.max_attachments = max_attachments

    @staticmethod
    def _walk(value: Any, seen: set[int] | None = None):
        if seen is None:
            seen = set()
        marker = id(value)
        if isinstance(value, (dict, list, tuple, set)):
            if marker in seen:
                return
            seen.add(marker)
        if isinstance(value, dict):
            for key, item in value.items():
                yield from TenderAttachmentAnalyzer._walk(key, seen)
                yield from TenderAttachmentAnalyzer._walk(item, seen)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                yield from TenderAttachmentAnalyzer._walk(item, seen)
        elif isinstance(value, str):
            yield value

    @staticmethod
    def discover(raw_data: dict[str, Any] | None, max_attachments: int = 30) -> list[TenderAttachment]:
        if not raw_data or max_attachments <= 0:
            return []
        result: list[TenderAttachment] = []
        seen: set[str] = set()
        for value in TenderAttachmentAnalyzer._walk(raw_data):
            candidate = value.strip()
            if not candidate or len(candidate) > 4096:
                continue
            parsed = urlparse(candidate)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            normalized = candidate
            if normalized in seen:
                continue
            seen.add(normalized)
            filename = parsed.path.rsplit("/", 1)[-1] or None
            result.append(TenderAttachment(url=normalized, filename=filename))
            if len(result) >= max_attachments:
                break
        return result

    def analyze(
        self,
        raw_data: dict[str, Any] | None,
        keywords: list[str],
    ) -> list[TenderAttachmentAnalysis]:
        attachments = self.discover(raw_data, self.max_attachments)
        results: list[TenderAttachmentAnalysis] = []
        for attachment in attachments:
            downloaded = self.downloader.download(attachment.url, filename=attachment.filename)
            documents = tuple(self.intelligence.extract_bytes(downloaded.content, downloaded.filename))
            hits = tuple(self.intelligence.search(list(documents), keywords))
            results.append(
                TenderAttachmentAnalysis(
                    attachment=attachment,
                    downloaded=downloaded,
                    documents=documents,
                    hits=hits,
                )
            )
        return results
