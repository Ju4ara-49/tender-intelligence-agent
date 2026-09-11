"""Безопасная загрузка вложений для локального Document Intelligence."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


@dataclass(frozen=True)
class DownloadedDocument:
    filename: str
    content: bytes
    content_type: str
    source_url: str


class DocumentDownloadError(ValueError):
    pass


class DocumentDownloader:
    """HTTP(S)-загрузчик с лимитом размера и базовой SSRF-защитой."""

    def __init__(self, max_bytes: int = 50 * 1024 * 1024, timeout: float = 30.0, max_redirects: int = 5) -> None:
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.max_redirects = max_redirects

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(str(url).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DocumentDownloadError("Разрешены только HTTP/HTTPS URL")
        hostname = parsed.hostname.casefold()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
            raise DocumentDownloadError("Локальные адреса запрещены")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None and (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved):
            raise DocumentDownloadError("Приватные и локальные IP-адреса запрещены")

    def download(self, url: str, filename: str | None = None) -> DownloadedDocument:
        current_url = str(url).strip()
        with httpx.Client(timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)), follow_redirects=False) as client:
            for _ in range(self.max_redirects + 1):
                self._validate_url(current_url)
                response = client.get(current_url)
                if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise DocumentDownloadError("Сервер вернул редирект без Location")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > self.max_bytes:
                            raise DocumentDownloadError("Файл превышает лимит размера")
                    except ValueError:
                        pass
                content = response.content
                if len(content) > self.max_bytes:
                    raise DocumentDownloadError("Файл превышает лимит размера")
                final_url = str(response.url)
                self._validate_url(final_url)
                if not filename:
                    filename = final_url.rstrip("/").rsplit("/", 1)[-1] or "attachment.bin"
                return DownloadedDocument(
                    filename=filename[:255],
                    content=content,
                    content_type=response.headers.get("content-type", "").split(";", 1)[0].strip(),
                    source_url=final_url,
                )
        raise DocumentDownloadError("Слишком много HTTP-редиректов")
