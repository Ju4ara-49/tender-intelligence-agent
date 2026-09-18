from pathlib import Path

import pytest

from src.tenderplan.documents import (
    DocumentExtractionStatus,
    TenderDocumentStore,
    content_sha256,
)


def test_new_document_starts_at_version_one(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    digest = content_sha256(b"v1")

    doc = store.save(
        tender_key="eis:123",
        url="https://example.test/doc.pdf",
        filename="doc.pdf",
        sha256=digest,
    )

    assert doc.version == 1
    assert doc.sha256 == digest
    assert doc.extraction_status == DocumentExtractionStatus.PENDING


def test_same_url_and_hash_is_idempotent(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    digest = content_sha256(b"same")

    first = store.save(tender_key="eis:123", url="https://example.test/doc.pdf", sha256=digest)
    second = store.save(
        tender_key="eis:123",
        url="https://example.test/doc.pdf",
        filename="renamed.pdf",
        sha256=digest,
        extraction_status=DocumentExtractionStatus.EXTRACTED,
        extracted_text="text",
    )

    assert second == first
    assert len(store.list_for_tender("eis:123")) == 1


def test_same_url_with_new_hash_creates_next_version(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    first = store.save(
        tender_key="eis:123",
        url="https://example.test/doc.pdf",
        sha256=content_sha256(b"v1"),
    )
    second = store.save(
        tender_key="eis:123",
        url="https://example.test/doc.pdf",
        sha256=content_sha256(b"v2"),
    )

    assert first.version == 1
    assert second.version == 2
    assert [d.version for d in store.list_for_tender("eis:123")] == [1, 2]


def test_different_url_is_separate_document(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    first = store.save(
        tender_key="eis:123",
        url="https://example.test/a.pdf",
        sha256=content_sha256(b"a"),
    )
    second = store.save(
        tender_key="eis:123",
        url="https://example.test/b.pdf",
        sha256=content_sha256(b"b"),
    )

    assert first.document_id != second.document_id
    assert len(store.list_for_tender("eis:123")) == 2


def test_document_identity_is_scoped_to_tender(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    digest = content_sha256(b"same")
    first = store.save(tender_key="eis:123", url="https://example.test/doc.pdf", sha256=digest)
    second = store.save(tender_key="eis:124", url="https://example.test/doc.pdf", sha256=digest)

    assert first.document_id != second.document_id
    assert first.version == second.version == 1


def test_invalid_hash_is_rejected(tmp_path: Path):
    store = TenderDocumentStore(tmp_path / "agent.db")
    with pytest.raises(ValueError, match="SHA-256"):
        store.save(tender_key="eis:123", url="https://example.test/doc.pdf", sha256="bad")
