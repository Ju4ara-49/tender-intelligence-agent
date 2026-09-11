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


def test_cp1251_text_is_decoded():
    docs = DocumentIntelligence().extract_bytes("Закупаем подшипники".encode("cp1251"), "notice.txt")
    assert "подшипники" in docs[0].text


def test_html_markup_is_not_returned_as_document_text():
    data = "<html><script>secret()</script><body><h1>Подшипники</h1></body></html>".encode("utf-8")
    docs = DocumentIntelligence().extract_bytes(data, "notice.html")
    assert docs[0].text == "Подшипники"
    assert "script" not in docs[0].text.lower()


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


def test_windows_absolute_archive_path_is_blocked():
    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("C:\\Windows\\evil.txt", "bad")
    with pytest.raises(UnsafeArchiveError):
        DocumentIntelligence().extract_bytes(malicious.getvalue(), "bad.zip")


def test_nested_archive_is_processed_with_depth_limit():
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as archive:
        archive.writestr("notice.txt", "Глубокий документ")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as archive:
        archive.writestr("nested.zip", inner.getvalue())
    docs = DocumentIntelligence(max_nesting_depth=2).extract_bytes(outer.getvalue(), "outer.zip")
    assert any("Глубокий документ" in doc.text for doc in docs)
    with pytest.raises(UnsafeArchiveError):
        DocumentIntelligence(max_nesting_depth=1).extract_bytes(outer.getvalue(), "outer.zip")


def test_archive_uncompressed_limit():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", "0123456789")
    with pytest.raises(UnsafeArchiveError):
        DocumentIntelligence(max_archive_uncompressed=5).extract_bytes(buffer.getvalue(), "a.zip")


def test_office_zip_path_is_validated_before_openpyxl():
    malicious = io.BytesIO()
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../evil.txt", "bad")
    with pytest.raises(UnsafeArchiveError):
        DocumentIntelligence().extract_bytes(malicious.getvalue(), "bad.xlsx")
