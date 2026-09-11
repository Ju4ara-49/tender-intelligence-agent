"""Связка вложений тендера с локальным Document Intelligence.

Адаптер намеренно не привязан к конкретной площадке: разные сборщики называют
вложения по-разному. Он рекурсивно ищет HTTP(S)-ссылки только в raw_data,
скачивает их через SSRF-защищённый downloader и выполняет локальный поиск.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.documents.downloader import DocumentDownloader
from src.documents.intelligence import DocumentHit, DocumentIntelligence, DocumentText


@dataclass(frozen=True)
class TenderDocumentAnalysis:
    documents: list[DocumentText]
    hits: list[DocumentHit]
    urls: list[str]
    errors: list[str]


def _walk_urls(value: Any, *, _seen: set[int] | None = None) -> list[str]:
    """Найти URL в произвольной структуре raw_data без доверия к ключам."""
    seen = _seen if _seen is not None else set()
    if isinstance(value, str):
        candidate = value.strip()
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            return [candidate]
        return []
    if isinstance(value, Mapping):
        marker = id(value)
        if marker in seen:
            return []
        seen.add(marker)
        result: list[str] = []
        for item in value.values():
            result.extend(_walk_urls(item, _seen=seen))
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        marker = id(value)
        if marker in seen:
            return []
        seen.add(marker)
        result: list[str] = []
        for item in value:
            result.extend(_walk_urls(item, _seen=seen))
        return result
    return []


class TenderDocumentIntelligence:
    """Загрузить и локально проиндексировать доступные вложения тендера."""

    def __init__(self, downloader: DocumentDownloader | None = None, intelligence: DocumentIntelligence | None = None) -> None:
        self.downloader = downloader or DocumentDownloader()
        self.intelligence = intelligence or DocumentIntelligence()

    @staticmethod
    def attachment_urls(raw_data: Mapping[str, Any] | None) -> list[str]:
        urls = _walk_urls(raw_data or {})
        # Стабильный порядок и защита от повторной загрузки одного URL.
        return list(dict.fromkeys(urls))

    def analyze(self, raw_data: Mapping[str, Any] | None, keywords: list[str]) -> TenderDocumentAnalysis:
        documents: list[DocumentText] = []
        hits: list[DocumentHit] = []
        errors: list[str] = []
        urls = self.attachment_urls(raw_data)
        for url in urls:
            try:
                downloaded = self.downloader.download(url)
                documents.extend(self.intelligence.extract_bytes(downloaded.content, downloaded.filename))
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
        if documents and keywords:
            hits = self.intelligence.search(documents, keywords)
        return TenderDocumentAnalysis(documents=documents, hits=hits, urls=urls, errors=errors)
