"""Безопасная загрузка вложений для локального Document Intelligence."""
from __future__ import annotations

import ipaddress
import socket
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
    """HTTP(S)-загрузчик с лимитом размера, редиректами и SSRF-защитой."""

    def __init__(self, max_bytes: int = 50 * 1024 * 1024, timeout: float = 30.0, max_redirects: int = 5) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes должен быть положительным")
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.max_redirects = max_redirects

    @staticmethod
    def _validate_ip(address: str) -> None:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise DocumentDownloadError("Приватные и локальные IP-адреса запрещены")

    @classmethod
    def _validate_url(cls, url: str, resolve_dns: bool = False) -> None:
        parsed = urlparse(str(url).strip())
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise DocumentDownloadError("Разрешены только HTTP/HTTPS URL")
        hostname = parsed.hostname.rstrip(".").casefold()
        if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
            raise DocumentDownloadError("Локальные адреса запрещены")
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            address = None
        if address is not None:
            cls._validate_ip(str(address))
        elif resolve_dns:
            try:
                results = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
            except socket.gaierror as exc:
                raise DocumentDownloadError(f"Не удалось разрешить DNS-имя: {hostname}") from exc
            addresses = {item[4][0] for item in results if item[4]}
            if not addresses:
                raise DocumentDownloadError("DNS не вернул адрес")
            for resolved in addresses:
                cls._validate_ip(resolved)

    def download(self, url: str, filename: str | None = None) -> DownloadedDocument:
        current_url = str(url).strip()
        with httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=min(10.0, self.timeout)),
            follow_redirects=False,
        ) as client:
            for _ in range(self.max_redirects + 1):
                self._validate_url(current_url, resolve_dns=True)
                try:
                    response = client.stream("GET", current_url)
                    response.__enter__()
                except httpx.HTTPError as exc:
                    raise DocumentDownloadError(f"Ошибка загрузки документа: {exc}") from exc
                try:
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
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise DocumentDownloadError("Файл превышает лимит размера")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    final_url = str(response.url)
                    self._validate_url(final_url, resolve_dns=True)
                    if not filename:
                        filename = final_url.rstrip("/").rsplit("/", 1)[-1] or "attachment.bin"
                    return DownloadedDocument(
                        filename=filename[:255],
                        content=content,
                        content_type=response.headers.get("content-type", "").split(";", 1)[0].strip(),
                        source_url=final_url,
                    )
                except httpx.HTTPError as exc:
                    raise DocumentDownloadError(f"Ошибка загрузки документа: {exc}") from exc
                finally:
                    response.__exit__(None, None, None)
        raise DocumentDownloadError("Слишком много HTTP-редиректов")
