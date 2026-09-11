from datetime import datetime, timezone

from src.decision_card import render_decision_card
from src.models.tender import Tender, TenderAnalysis
from src.workflow import WorkflowState


def test_decision_card_is_compact_and_does_not_invent_missing_fields():
    tender = Tender(
        platform="b2b_center",
        external_id="123",
        title="Подшипники <оптом>",
        url="https://example.test/tender/123?a=1&b=2",
        price=1500000,
        deadline=datetime.now(timezone.utc),
        customer="ООО \"Заказчик\"",
    )
    analysis = TenderAnalysis(82, "Подходит по товару", "participate", ["Нужно проверить ТЗ"])
    workflow = WorkflowState(1, "42", "review", ["важный"], "Проверить наличие", "")
    card = render_decision_card(tender, analysis, workflow)
    assert "Подшипники &lt;оптом&gt;" in card
    assert "1 500 000 ₽" in card
    assert "Постоплата: <b>не указана</b>" in card
    assert "AI-релевантность: <b>82/100</b>" in card
    assert "На рассмотрении" in card
    assert "https://example.test/tender/123?a=1&amp;b=2" in card
