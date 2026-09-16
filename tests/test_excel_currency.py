from src.export.excel import export_tenders_to_excel
from src.models.tender import Tender
from src.storage.database import TenderDatabase


def test_excel_price_format_is_currency_neutral(tmp_path):
    db = TenderDatabase(tmp_path / "currency.db")
    tender = Tender(
        platform="test",
        external_id="currency-1",
        title="Non-RUB tender",
        url="https://example.test/currency-1",
        price=1234.56,
        currency="USD",
    )
    tender_id = db.save_tender(tender)

    output = export_tenders_to_excel(db, tmp_path / "currency.xlsx", tender_ids=[tender_id])

    from openpyxl import load_workbook

    workbook = load_workbook(output, data_only=False)
    sheet = workbook["Тендеры"]

    assert sheet["F2"].value == 1234.56
    assert sheet["G2"].value == "USD"
    assert sheet["F2"].number_format == "#,##0.00"
    assert "₽" not in sheet["F2"].number_format
