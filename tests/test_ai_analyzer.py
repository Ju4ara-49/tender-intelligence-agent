from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

from src.ai.analyzer import OllamaModelNotFoundError, OllamaResponseError, TenderAnalyzer
from src.models.tender import Tender


def _make_tender() -> Tender:
    return Tender(
        platform="eis",
        external_id="0001",
        title="Поставка полумуфт",
        url="https://example.com/tender/0001",
        customer="ООО Заказчик",
        price=150000,
        currency="RUB",
    )


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text

    def json(self):
        if self._json_data is None:
            raise ValueError("no json")
        return self._json_data


class TenderAnalyzerTests(unittest.TestCase):
    def test_module_is_importable_and_used_by_orchestrator(self) -> None:
        from src.orchestrator import Orchestrator  # noqa: F401

    def test_successful_ollama_chat_call_is_parsed(self) -> None:
        analyzer = TenderAnalyzer(model="qwen3:8b", ollama_url="http://localhost:11434")
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "message": {
                    "content": (
                        '{"relevance_score": 80, "summary": "ок", '
                        '"recommendation": "participate", "risks": [], '
                        '"budget_note": "", "deadline_note": ""}'
                    )
                }
            },
        )
        with patch("src.ai.analyzer.requests.post", return_value=fake_response) as mock_post:
            analysis = analyzer.analyze(_make_tender())

        self.assertEqual(analysis.relevance_score, 80)
        self.assertEqual(analysis.recommendation, "participate")
        self.assertFalse(analysis.is_stub)
        called_url = mock_post.call_args.args[0]
        self.assertTrue(called_url.endswith("/api/chat"))

    def test_strips_qwen3_think_block_before_parsing_json(self) -> None:
        analyzer = TenderAnalyzer(model="qwen3:8b", ollama_url="http://localhost:11434")
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "message": {
                    "content": (
                        "<think>рассуждения модели</think>"
                        '{"relevance_score": 40, "summary": "ок", '
                        '"recommendation": "review", "risks": [], '
                        '"budget_note": "", "deadline_note": ""}'
                    )
                }
            },
        )
        with patch("src.ai.analyzer.requests.post", return_value=fake_response):
            analysis = analyzer.analyze(_make_tender())
        self.assertEqual(analysis.relevance_score, 40)

    def test_model_not_found_raises_clear_error_without_stub(self) -> None:
        analyzer = TenderAnalyzer(
            model="does-not-exist", ollama_url="http://localhost:11434", use_stub_when_no_key=False
        )
        fake_response = _FakeResponse(status_code=404, text="model 'does-not-exist' not found")
        with patch("src.ai.analyzer.requests.post", return_value=fake_response):
            with self.assertRaises(OllamaModelNotFoundError) as ctx:
                analyzer.analyze(_make_tender())
        self.assertIn("ollama pull", str(ctx.exception))

    def test_endpoint_404_is_not_misdiagnosed_as_missing_model(self) -> None:
        analyzer = TenderAnalyzer(
            model="qwen3:8b", ollama_url="http://localhost:11434", use_stub_when_no_key=False
        )
        fake_response = _FakeResponse(status_code=404, text="404 page not found")
        with patch("src.ai.analyzer.requests.post", return_value=fake_response):
            with self.assertRaises(OllamaResponseError) as ctx:
                analyzer.analyze(_make_tender())
        self.assertIn("endpoint", str(ctx.exception))

    def test_connection_error_falls_back_to_stub_when_allowed(self) -> None:
        analyzer = TenderAnalyzer(
            model="qwen3:8b", ollama_url="http://localhost:11434", use_stub_when_no_key=True
        )
        with patch(
            "src.ai.analyzer.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            analysis = analyzer.analyze(_make_tender())
        self.assertTrue(analysis.is_stub)
        self.assertEqual(analysis.recommendation, "review")

    def test_connection_error_raises_when_stub_not_allowed(self) -> None:
        analyzer = TenderAnalyzer(
            model="qwen3:8b", ollama_url="http://localhost:11434", use_stub_when_no_key=False
        )
        with patch(
            "src.ai.analyzer.requests.post",
            side_effect=requests.exceptions.ConnectionError("refused"),
        ):
            with self.assertRaises(Exception):
                analyzer.analyze(_make_tender())

    def test_malformed_json_response_is_reported_clearly(self) -> None:
        analyzer = TenderAnalyzer(
            model="qwen3:8b", ollama_url="http://localhost:11434", use_stub_when_no_key=True
        )
        fake_response = _FakeResponse(
            status_code=200, json_data={"message": {"content": "это не json"}}
        )
        with patch("src.ai.analyzer.requests.post", return_value=fake_response):
            analysis = analyzer.analyze(_make_tender())
        self.assertTrue(analysis.is_stub)
        self.assertIn("JSON", analysis.summary)

    def test_non_numeric_score_becomes_stub_instead_of_crashing_pipeline(self) -> None:
        analyzer = TenderAnalyzer(
            model="qwen3:8b", ollama_url="http://localhost:11434", use_stub_when_no_key=True
        )
        fake_response = _FakeResponse(
            status_code=200,
            json_data={"message": {"content": '{"relevance_score":"unknown","recommendation":"participate"}'}},
        )
        with patch("src.ai.analyzer.requests.post", return_value=fake_response):
            analysis = analyzer.analyze(_make_tender())
        self.assertTrue(analysis.is_stub)
        self.assertIn("relevance_score", analysis.summary)

    def test_invalid_recommendation_and_risks_are_normalized(self) -> None:
        analyzer = TenderAnalyzer(model="qwen3:8b", ollama_url="http://localhost:11434")
        fake_response = _FakeResponse(
            status_code=200,
            json_data={
                "message": {
                    "content": '{"relevance_score":150,"recommendation":"maybe","risks":"Есть риск"}'
                }
            },
        )
        with patch("src.ai.analyzer.requests.post", return_value=fake_response):
            analysis = analyzer.analyze(_make_tender())
        self.assertEqual(analysis.relevance_score, 100)
        self.assertEqual(analysis.recommendation, "review")
        self.assertEqual(analysis.risks, ["Есть риск"])


if __name__ == "__main__":
    unittest.main()
