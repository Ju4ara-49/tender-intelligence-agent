"""AI-анализ тендеров через локальный Ollama (без облачных API)."""

from __future__ import annotations

import json
import logging
import re

import requests

from src.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from src.models.tender import Tender, TenderAnalysis

logger = logging.getLogger(__name__)

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)

_REQUEST_TIMEOUT_SECONDS = 120
_MAX_ATTEMPTS = 2


class OllamaUnavailableError(RuntimeError):
    """Ollama недоступен по сети (сервис не запущен / хост не отвечает)."""


class OllamaModelNotFoundError(RuntimeError):
    """Указанная модель не установлена в Ollama."""


class OllamaResponseError(RuntimeError):
    """Ollama ответил, но ответ пустой/некорректный/не парсится как JSON."""


class TenderAnalyzer:
    """Анализирует тендеры локальной моделью Ollama (qwen3:8b по умолчанию)."""

    def __init__(
        self,
        model: str,
        ai_context: str = "",
        use_stub_when_no_key: bool = False,
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self.ai_context = ai_context or ""
        self.use_stub_when_no_key = use_stub_when_no_key
        self.ollama_url = (ollama_url or "http://localhost:11434").rstrip("/")

    @property
    def is_configured(self) -> bool:
        """Локальный Ollama не требует ключа — «настроен», если заданы url и модель."""
        return bool(self.model) and bool(self.ollama_url)

    def _build_tender_text(self, tender: Tender) -> str:
        lines = [
            f"Площадка: {tender.platform}",
            f"Название: {tender.title}",
        ]
        if tender.customer:
            lines.append(f"Заказчик: {tender.customer}")
        if tender.region:
            lines.append(f"Регион: {tender.region}")
        if tender.price is not None:
            lines.append(f"Начальная цена: {tender.price} {tender.currency}")
        if tender.deadline is not None:
            lines.append(f"Срок подачи: {tender.deadline.isoformat()}")
        if tender.law_type:
            lines.append(f"Тип закупки: {tender.law_type}")
        if tender.advance_required:
            lines.append(f"Аванс: да ({tender.advance_percent or '?'}%)")
        description = tender.full_text or tender.description
        if description:
            lines.append(f"Описание/предмет закупки: {description}")
        return "\n".join(lines)

    def _call_ollama(self, user_prompt: str) -> str:
        """Один HTTP-запрос к /api/chat. Бросает понятные исключения при ошибках."""
        url = f"{self.ollama_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.2},
        }

        try:
            response = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SECONDS)
        except requests.exceptions.ConnectionError as exc:
            raise OllamaUnavailableError(
                f"Не удалось подключиться к Ollama по адресу {self.ollama_url}. "
                "Проверьте, что Ollama запущен (`ollama serve`)."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise OllamaUnavailableError(
                f"Ollama не ответил за {_REQUEST_TIMEOUT_SECONDS} сек. "
                "Возможно, модель ещё загружается или сервис перегружен."
            ) from exc

        if response.status_code == 404:
            raise OllamaModelNotFoundError(
                f"Ollama вернул 404 для модели '{self.model}' по адресу {url}. "
                f"Убедитесь, что модель установлена: `ollama pull {self.model}`, "
                "и что используется endpoint /api/chat (не устаревший /api/generate)."
            )
        if response.status_code >= 400:
            raise OllamaResponseError(
                f"Ollama вернул HTTP {response.status_code}: {response.text[:300]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise OllamaResponseError(
                f"Ollama вернул не-JSON ответ: {response.text[:300]}"
            ) from exc

        message = data.get("message") or {}
        content = message.get("content")
        if not content or not str(content).strip():
            raise OllamaResponseError("Ollama вернул пустой ответ (message.content пуст).")
        return str(content)

    def _parse_model_output(self, content: str) -> dict:
        cleaned = _THINK_BLOCK_RE.sub("", content).strip()
        try:
            return json.loads(cleaned)
        except ValueError:
            pass

        match = _JSON_OBJECT_RE.search(cleaned)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                pass

        raise OllamaResponseError(
            f"Не удалось разобрать JSON в ответе модели: {cleaned[:300]}"
        )

    def _stub_analysis(self, reason: str) -> TenderAnalysis:
        logger.warning("AI: используется stub-анализ. Причина: %s", reason)
        return TenderAnalysis(
            relevance_score=50,
            summary=f"AI недоступен, использован stub-анализ. Причина: {reason}",
            recommendation="review",
            risks=["AI-анализ не выполнен, требуется ручная проверка"],
            budget_note="",
            deadline_note="",
            is_stub=True,
        )

    def analyze(self, tender: Tender) -> TenderAnalysis:
        """Анализирует тендер. При недоступности Ollama либо явно падает,
        либо (если разрешено конфигом) возвращает помеченный stub — но не молча."""
        user_prompt = build_user_prompt(self._build_tender_text(tender), self.ai_context)

        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                content = self._call_ollama(user_prompt)
                parsed = self._parse_model_output(content)
                return TenderAnalysis(
                    relevance_score=parsed.get("relevance_score", 0),
                    summary=str(parsed.get("summary", "")).strip(),
                    recommendation=str(parsed.get("recommendation", "review")).strip(),
                    risks=parsed.get("risks", []) or [],
                    budget_note=str(parsed.get("budget_note", "")).strip(),
                    deadline_note=str(parsed.get("deadline_note", "")).strip(),
                    is_stub=False,
                )
            except OllamaModelNotFoundError as exc:
                last_error = exc
                logger.error("AI: %s", exc)
                break
            except (OllamaUnavailableError, OllamaResponseError) as exc:
                last_error = exc
                logger.warning(
                    "AI: попытка %d/%d не удалась: %s", attempt, _MAX_ATTEMPTS, exc
                )

        assert last_error is not None
        if self.use_stub_when_no_key:
            return self._stub_analysis(str(last_error))
        raise last_error
