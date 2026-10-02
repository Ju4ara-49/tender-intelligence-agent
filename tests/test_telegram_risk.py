from datetime import datetime, timezone
from src.models.tender import Tender, TenderAnalysis
from src.notifications.telegram import TelegramNotifier

def test_telegram_contains_deterministic_risk():
    tender=Tender(platform="eis",external_id="1",title="Поставка",url="https://x",
                  raw_data={"risk_assessment":{"level":"HIGH","factors":[{"code":"short_deadline"}]}})
    analysis=TenderAnalysis(relevance_score=90,summary="ok",recommendation="participate")
    message=TelegramNotifier.format_message(tender,analysis)
    assert "Risk Engine" in message
    assert "HIGH" in message
    assert "short_deadline" in message
