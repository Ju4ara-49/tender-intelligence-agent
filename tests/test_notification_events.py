from datetime import datetime, timedelta, timezone

from src.models.tender import Tender
from src.storage.database import TenderDatabase


def make_tender(tmp_path, price=1_000_000.0, deadline_days=10):
    db = TenderDatabase(tmp_path / "test.db")
    tender = Tender(
        platform="test",
        external_id="123",
        title="Поставка подшипников",
        url="https://example.test/tender/123",
        price=price,
        deadline=datetime.now(timezone.utc) + timedelta(days=deadline_days),
        region="Санкт-Петербург",
        customer="Тестовый заказчик",
        law_type="223-ФЗ",
    )
    return db, tender


def test_same_tender_state_is_not_notified_twice(tmp_path):
    db, tender = make_tender(tmp_path)
    tender_id = db.save_tender(tender)

    assert db.was_notified(tender.unique_key) is False
    db.mark_notified(tender_id)
    assert db.was_notified(tender.unique_key) is True

    # Повторная доставка того же состояния запрещена.
    db.mark_notified(tender_id)
    assert db.count_notifications() == 1


def test_changed_price_creates_new_notification_event(tmp_path):
    db, tender = make_tender(tmp_path, price=1_000_000.0)
    tender_id = db.save_tender(tender)
    db.mark_notified(tender_id)
    assert db.was_notified(tender.unique_key) is True

    # Изменение НМЦК должно считаться новым событием.
    tender.price = 1_200_000.0
    same_id = db.save_tender(tender)
    assert same_id == tender_id
    assert db.was_notified(tender.unique_key) is False

    db.mark_notified(tender_id)
    assert db.was_notified(tender.unique_key) is True
    assert db.count_notifications() == 2


def test_changed_deadline_creates_new_notification_event(tmp_path):
    db, tender = make_tender(tmp_path, deadline_days=10)
    tender_id = db.save_tender(tender)
    db.mark_notified(tender_id)

    tender.deadline = datetime.now(timezone.utc) + timedelta(days=20)
    db.save_tender(tender)

    assert db.was_notified(tender.unique_key) is False
