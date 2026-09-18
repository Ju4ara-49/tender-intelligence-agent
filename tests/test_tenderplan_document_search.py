from pathlib import Path

from src.tenderplan import DocumentExtractionStatus, TenderDocumentIngestor, TenderDocumentStore, content_sha256


def test_document_search_and_change_events(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    first = store.save(
        tender_key="eis:123",
        url="https://example.test/spec.pdf",
        sha256=content_sha256(b"bearings first"),
        extraction_status=DocumentExtractionStatus.EXTRACTED,
        extracted_text="Technical specification: bearings",
    )
    second = store.save(
        tender_key="eis:123",
        url="https://example.test/spec.pdf",
        sha256=content_sha256(b"bearings second"),
        extraction_status=DocumentExtractionStatus.EXTRACTED,
        extracted_text="Updated specification: seals",
    )

    assert first.version == 1
    assert second.version == 2
    assert [doc.version for doc in store.search("BEARINGS")] == [1]
    assert [doc.version for doc in store.search("seals", tender_key="eis:123")] == [2]

    events = store.events_for_tender("eis:123")
    assert [event["event_type"] for event in events] == ["created", "changed"]
    assert events[-1]["old_version"] == 1
    assert events[-1]["new_version"] == 2
    assert events[-1]["old_sha256"] == first.sha256
    assert events[-1]["new_sha256"] == second.sha256


def test_pdf_docx_and_xlsx_extraction(tmp_path: Path):
    import zipfile
    from io import BytesIO
    from openpyxl import Workbook
    from pypdf import PdfWriter

    store = TenderDocumentStore(tmp_path / "agent.db")
    ingestor = TenderDocumentIngestor(store)

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = BytesIO()
    writer.write(pdf)
    text, status = ingestor._extract(pdf.getvalue(), "application/pdf", "spec.pdf")
    assert status == DocumentExtractionStatus.EXTRACTED
    assert text == ""

    document_xml = b"""<?xml version="1.0"?><document xmlns="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><body><p><r><t>Contract requirements</t></r></p></body></document>"""
    docx = BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    text, status = ingestor._extract(docx.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "spec.docx")
    assert status == DocumentExtractionStatus.EXTRACTED
    assert "Contract requirements" in text

    workbook = Workbook()
    sheet = workbook.active
    sheet["A1"] = "Bearing"
    sheet["B1"] = "10 pcs"
    xlsx = BytesIO()
    workbook.save(xlsx)
    text, status = ingestor._extract(
        xlsx.getvalue(),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "items.xlsx",
    )
    assert status == DocumentExtractionStatus.EXTRACTED
    assert "Bearing" in text
    assert "10 pcs" in text
