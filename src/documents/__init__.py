"""Локальная обработка документов тендеров."""

from src.documents.downloader import DocumentDownloadError, DocumentDownloader, DownloadedDocument
from src.documents.intelligence import DocumentHit, DocumentIntelligence, DocumentText, UnsafeArchiveError
from src.documents.tender_attachments import TenderAttachment, TenderAttachmentAnalysis, TenderAttachmentAnalyzer

__all__ = [
    "DocumentDownloadError",
    "DocumentDownloader",
    "DocumentHit",
    "DocumentIntelligence",
    "DocumentText",
    "DownloadedDocument",
    "TenderAttachment",
    "TenderAttachmentAnalysis",
    "TenderAttachmentAnalyzer",
    "UnsafeArchiveError",
]
