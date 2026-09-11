import io
import zipfile

import pytest
from openpyxl import Workbook

from src.documents.intelligence import DocumentIntelligence, UnsafeArchiveError


def test_text_extraction_and_keyword_hits():
    service = DocumentIntelligence()
    docs = service.extract_bytes("Закупаем подшипники и муфты.".encode(), "notice.txt")
    hits = service.search(docs, ["подшипники", "муфты"])
    assert len(hits) == 2
    assert hits[0].path == "notice.txt"
    assert "подшипники" in hits[0].snippet


def test_xlsx_extraction():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Товары"
    sheet.append(["Наименование", "Количество"])
    sheet.append(["Подшипник 6205", 12])
    buffer = io.BytesIO()
    workbook.save(buffer)

    docs = DocumentIntelligence().extract_bytes(buffer.getvalue(), "spec.xlsx")
    assert "Подшипник 6205" in docs[0].text
    assert "Количество" in docs[0].text


def test_archive_extraction_and_path_traversal_block():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("docs/notice.txt", "Муфта МУВП")
    docs = DocumentIntelligence().extract_bytes(buffer.getvalue(), "docs.zip")
    assert docs[0].path == "docs.zip!/docs/notice.txt"
    assert "МУВП" in docs[0].text

    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../../evil.txt", "bad")
    with pytest.raises(UnsafeArchiveError):
        DocumentIntelligence().extract_bytes(malicious.getvalue(), "bad.zip")


def test_archive_uncompressed_limit():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", "0123456789")
    with pytest.raises(UnsafeArchiveError):
        DocumentIntelligence(max_archive_uncompressed=5).extract_bytes(buffer.getvalue(), "a.zip")
