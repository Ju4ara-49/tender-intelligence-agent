from src.models.tender import Tender
from src.storage.database import TenderDatabase


def test_database_notification_fingerprint_changes_when_description_changes(tmp_path):
    db = TenderDatabase(tmp_path / "description.db")
    tender = Tender(
        platform="test",
        external_id="description-db-1",
        title="Поставка подшипников",
        url="https://example.test/description-db-1",
        price=100000,
        description="Первая редакция условий.",
    )
    tender_id = db.save_tender(tender)
    db.mark_notified(tender_id)
    assert db.was_notified(tender.unique_key) is True

    tender.description = "Вторая редакция условий с существенным изменением."
    db.save_tender(tender)

    assert db.was_notified(tender.unique_key) is False
    db.mark_notified(tender_id)
    assert db.was_notified(tender.unique_key) is True
    assert db.count_notifications() == 2
