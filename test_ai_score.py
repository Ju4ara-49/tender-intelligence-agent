from src.ai.analyzer import TenderAnalyzer
from src.models.tender import Tender

tender = Tender(
    platform="eis_zakupki",
    external_id="TEST-SOFTWARE-001",
    title="Поставка программного обеспечения",
    url="https://example.com",
    description="""
    Поставка программного обеспечения для организации.
    Предоставление неисключительного права использования программного продукта.
    Количество лицензий: 10.
    Цена и условия поставки определяются документацией.
    """,
    price=100000,
    customer="Тестовый заказчик",
    region="Москва",
)

analyzer = TenderAnalyzer(
    model="qwen3:8b",
    ollama_url="http://localhost:11434",
    use_stub_when_no_key=False,
)

result = analyzer.analyze(tender)

print()
print("=" * 60)
print("РЕЗУЛЬТАТ ТЕСТА")
print("=" * 60)
print("score:", result.relevance_score)
print("recommendation:", result.recommendation)
print("stub:", result.is_stub)
print("summary:", result.summary)
print("risks:", result.risks)
print("=" * 60)
