from src.models.tender import Tender
from src.orchestrator import Orchestrator
from src.telegram_settings import TenderCriteria


def make_tender(*, advance_required: bool, advance_percent: float | None) -> Tender:
    return Tender(
        platform="test",
        external_id="advance-filter",
        title="Поставка запасных частей",
        url="https://example.test/tender/advance-filter",
        price=100_000,
        advance_required=advance_required,
        advance_percent=advance_percent,
    )


def test_advance_required_does_not_require_known_percent() -> None:
    tender = make_tender(advance_required=True, advance_percent=None)
    criteria = TenderCriteria(
        advance_required=True,
        min_advance_percent=0,
        min_submission_days=0,
    )

    assert Orchestrator._passes_criteria(tender, criteria) == (True, "")


def test_min_advance_percent_requires_known_percent() -> None:
    tender = make_tender(advance_required=True, advance_percent=None)
    criteria = TenderCriteria(
        advance_required=True,
        min_advance_percent=10,
        min_submission_days=0,
    )

    assert Orchestrator._passes_criteria(tender, criteria) == (False, "min_advance_percent")


def test_advance_required_rejects_tender_without_advance() -> None:
    tender = make_tender(advance_required=False, advance_percent=None)
    criteria = TenderCriteria(
        advance_required=True,
        min_submission_days=0,
    )

    assert Orchestrator._passes_criteria(tender, criteria) == (False, "advance_required")
