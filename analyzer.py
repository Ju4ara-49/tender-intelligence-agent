"""AI-анализ тендеров через локальную модель Ollama."""

from __future__ import annotations

import json
import logging
import re

import httpx

from src.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from src.models.tender import Tender, TenderAnalysis

logger = logging.getLogger(__name__)


class TenderAnalyzer:
    """
    Анализатор тендеров через локальную модель Ollama.

    Основной режим:
        локальная модель Qwen3.

    OpenAI API не используется.
    """

    # ФИКС 19.08.2026: было 6000 — вместе с system-промптом (~11200
    # символов) и старым дублирующим user-промптом (~6500 символов)
    # это уже само по себе превышало num_ctx=8192 у Ollama ДО того,
    # как в текст добавлялся сам тендер. Модель получала обрезанный
    # контекст, и это объясняет нестабильный/заниженный score.
    MAX_TENDER_TEXT = 10000
    OLLAMA_TIMEOUT = 90.0

    # Было 3500 — реальным ограничителем длины была именно эта
    # константа (MAX_TENDER_TEXT почти никогда не срабатывал,
    # см. _build_tender_text). Из-за этого длинные карточки ЕИС
    # обрезались до того, как AI успевал увидеть количество/цену
    # за единицу — и уходил в "недостаточно данных" -> заниженный
    # score.
    DESCRIPTION_LIMIT = 8000

    # Контекстное окно Ollama. Было 8192 — недостаточно с учётом
    # объёма промптов (см. выше). qwen3:8b штатно тянет более
    # длинный контекст. Если на конкретной машине не хватает
    # памяти/VRAM и Ollama падает по OOM — уменьшить это значение,
    # а не возвращать старые лимиты текста.
    # 20480 вместо 16384: точный расход токенов на кириллице у
    # qwen3-токенизатора я не могу проверить без доступа к живому
    # Ollama (нет сети в этой среде). Оценка по символам говорит,
    # что 16384 должно хватать почти всегда, но лучше взять запас.
    # ОБЯЗАТЕЛЬНО проверить на реальном запуске: если Ollama выдаёт
    # ошибку по памяти/OOM — уменьшать именно это число, а не
    # возвращать лимиты текста к старым значениям.
    NUM_CTX = 20480

    # Qwen иногда не успевает закончить JSON при слишком маленьком
    # лимите токенов. 250 было недостаточно.
    FIRST_NUM_PREDICT = 500
    RETRY_NUM_PREDICT = 350

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "https://api.openai.com/v1",
        model: str = "qwen3:8b",
        ai_context: str = "",
        use_stub_when_no_key: bool = True,
        ollama_url: str = "http://localhost:11434",
    ) -> None:
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model or "qwen3:8b"
        self.ai_context = ai_context
        self.use_stub_when_no_key = use_stub_when_no_key
        self.ollama_url = ollama_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        """Локальный AI считается настроенным, если указан Ollama URL."""
        return bool(self.ollama_url)

    def analyze(self, tender: Tender) -> TenderAnalysis:
        """Анализировать один тендер через Ollama."""

        try:
            return self._call_ollama(tender)

        except Exception as exc:
            logger.error(
                "AI: ошибка анализа %s через Ollama: %s",
                tender.unique_key,
                exc,
            )

            if self.use_stub_when_no_key:
                return self._stub_analysis(
                    tender,
                    note=f"Ollama недоступна: {exc}",
                )

            raise

    def _build_tender_text(self, tender: Tender) -> str:
        """Сформировать короткий текст тендера."""

        description = tender.description or ""

        description = re.sub(
            r"\s+",
            " ",
            description,
        ).strip()

        description = description[: self.DESCRIPTION_LIMIT]

        deadline = (
            tender.deadline.isoformat()
            if tender.deadline
            else "не указан"
        )

        text = (
            f"Название: {tender.title or 'не указано'}\n"
            f"Заказчик: {tender.customer or 'не указан'}\n"
            f"Регион: {tender.region or 'не указан'}\n"
            f"Цена: "
            f"{tender.price if tender.price is not None else 'не указана'} "
            f"{tender.currency or ''}\n"
            f"Срок подачи заявки: {deadline}\n"
            f"Описание: {description}"
        )

        return text[: self.MAX_TENDER_TEXT]

    def _ollama_request(
        self,
        messages: list[dict[str, str]],
        num_predict: int,
    ) -> str:
        """Выполнить один запрос к Ollama."""

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0.0,
                "num_predict": num_predict,
                "num_ctx": self.NUM_CTX,
            },
        }

        with httpx.Client(
            timeout=self.OLLAMA_TIMEOUT
        ) as client:

            response = client.post(
                f"{self.ollama_url}/api/chat",
                json=payload,
            )

            response.raise_for_status()

            data = response.json()

        content = (
            data.get("message", {})
            .get("content", "")
        )

        if not content:
            raise ValueError(
                "Ollama вернула пустой ответ"
            )

        return str(content).strip()

    def _call_ollama(self, tender: Tender) -> TenderAnalysis:
        """Отправить тендер в Ollama."""

        tender_text = self._build_tender_text(tender)

        # ФИКС 19.08.2026: раньше сборка промпта дублировала
        # инструкции system-промпта в собственном user-промпте
        # (~6500 лишних символов) и никогда не передавала
        # self.ai_context в модель — критерии клиента из
        # keywords.yaml (ai_context) на сам запрос к Qwen не влияли.
        # build_user_prompt() уже умеет вставлять ai_context и не
        # дублирует SYSTEM_PROMPT.
        user_prompt = build_user_prompt(
            tender_text,
            self.ai_context,
        )

        logger.info(
            "AI: анализ тендера %s | tender_text=%d chars | "
            "system=%d chars | user=%d chars | ai_context=%s",
            tender.external_id,
            len(tender_text),
            len(SYSTEM_PROMPT),
            len(user_prompt),
            "да" if self.ai_context else "нет (пусто)",
        )

        # ----------------------------------------------------------
        # ОСНОВНОЙ ЗАПРОС
        # ----------------------------------------------------------

        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ]

        content = self._ollama_request(
            messages,
            num_predict=self.FIRST_NUM_PREDICT,
        )

        try:
            parsed = self._parse_json_response(
                content
            )

        except Exception as first_error:

            logger.warning(
                "AI: первый JSON не удалось разобрать: %s",
                first_error,
            )

            # ------------------------------------------------------
            # ПОВТОРНЫЙ ЗАПРОС
            # ------------------------------------------------------

            logger.info(
                "AI: выполняем повторный запрос с минимальным JSON"
            )

            retry_messages = [
                {
                    "role": "system",
                    "content": (
                        "Ты возвращаешь только валидный JSON. "
                        "Никакого другого текста. "
                        "Ответ должен быть полностью завершён."
                    ),
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ]

            retry_content = self._ollama_request(
                retry_messages,
                num_predict=self.RETRY_NUM_PREDICT,
            )

            parsed = self._parse_json_response(
                retry_content
            )

        logger.info(
            "AI: успешный анализ %s",
            tender.external_id,
        )

        logger.info(
            "AI: РЕЗУЛЬТАТ QWEN %s: %s",
            tender.external_id,
            json.dumps(parsed, ensure_ascii=False),
        )

        relevance_score = self._safe_int(
            parsed.get(
                "relevance_score",
                50,
            ),
            default=50,
        )
        if relevance_score >= 80:
            recommendation = "participate"
        elif relevance_score >= 50:
            recommendation = "review"
        else:
            recommendation = "skip"

        return TenderAnalysis(
            relevance_score=relevance_score,
            summary=self._clean_text(
                parsed.get(
                    "summary",
                    "",
                ),
                max_length=500,
            ),
            recommendation=recommendation,
            risks=self._safe_list(
                parsed.get(
                    "risks",
                    [],
                )
            )[:2],
            budget_note=self._clean_text(
                parsed.get(
                    "budget_note",
                    "",
                ),
                max_length=300,
            ),
            deadline_note=self._clean_text(
                parsed.get(
                    "deadline_note",
                    "",
                ),
                max_length=300,
            ),
            is_stub=False,
        )

    @staticmethod
    def _parse_json_response(
        content: str,
    ) -> dict:
        """Разобрать JSON от Ollama."""

        content = content.strip()

        if not content:
            raise ValueError(
                "AI вернул пустой ответ"
            )

        if content.startswith("```"):
            content = re.sub(
                r"^```(?:json)?\s*",
                "",
                content,
                flags=re.IGNORECASE,
            )

            content = re.sub(
                r"\s*```$",
                "",
                content,
            )

        content = content.strip()

        # Основная попытка.
        try:
            parsed = json.loads(content)

            if not isinstance(parsed, dict):
                raise ValueError(
                    "AI вернул не JSON-объект"
                )

            return parsed

        except json.JSONDecodeError:
            pass

        # Иногда модель может добавить текст вокруг JSON.
        start = content.find("{")
        end = content.rfind("}")

        if (
            start == -1
            or end == -1
            or end <= start
        ):
            raise ValueError(
                "AI вернул некорректный JSON: "
                f"{content[:500]}"
            )

        candidate = content[
            start : end + 1
        ]

        try:
            parsed = json.loads(candidate)

        except json.JSONDecodeError as exc:
            raise ValueError(
                f"AI вернул некорректный JSON: {exc}"
            ) from exc

        if not isinstance(parsed, dict):
            raise ValueError(
                "JSON не является объектом"
            )

        return parsed

    @staticmethod
    def _clean_text(
        value,
        max_length: int,
    ) -> str:
        """Очистить текст."""

        if value is None:
            return ""

        text = str(value)

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text[:max_length]

    @staticmethod
    def _normalize_recommendation(
        value,
    ) -> str:
        """Нормализовать рекомендацию."""

        value = str(
            value
        ).strip().lower()

        if value not in {
            "participate",
            "review",
            "skip",
        }:
            return "review"

        return value

    @staticmethod
    def _stub_analysis(
        tender: Tender,
        note: str = "",
    ) -> TenderAnalysis:
        """Базовая оценка без AI."""

        text = tender.full_text.lower()

        score = 60

        positive = (
            "it",
            "программ",
            "информацион",
            "разработ",
            "облач",
            "автомоб",
            "мерседес",
            "запчаст",
            "ремонт",
            "техническ",
            "оборудован",
            "комплектующ",
            "детал",
            "подшипник",
            "насос",
            "компрессор",
            "муфт",
            "втулк",
            "электротех",
            "автоматик",
        )

        negative = (
            "утилиз",
            "мусор",
            "крематор",
        )

        for word in positive:
            if word in text:
                score += 5

        for word in negative:
            if word in text:
                score -= 20

        score = max(
            0,
            min(
                100,
                score,
            ),
        )

        summary = (
            f"[Заглушка AI] "
            f"{tender.title[:200]}. "
            "Локальный AI временно недоступен."
        )

        if note:
            summary += (
                f" ({note[:300]})"
            )

        recommendation = (
            "participate"
            if score >= 70
            else "review"
            if score >= 50
            else "skip"
        )

        return TenderAnalysis(
            relevance_score=score,
            summary=summary,
            recommendation=recommendation,
            risks=[
                "Анализ выполнен без локальной AI-модели."
            ],
            budget_note="",
            deadline_note="",
            is_stub=True,
        )

    @staticmethod
    def _safe_int(
        value,
        default: int = 50,
    ) -> int:
        """Безопасно преобразовать оценку."""

        try:
            value = int(value)

        except (
            TypeError,
            ValueError,
        ):
            return default

        return max(
            0,
            min(
                100,
                value,
            ),
        )

    @staticmethod
    def _safe_list(
        value,
    ) -> list[str]:
        """Привести риски к списку."""

        if value is None:
            return []

        if isinstance(
            value,
            list,
        ):
            result = []

            for item in value:
                text = str(
                    item
                ).strip()

                if text:
                    result.append(
                        text[:300]
                    )

            return result

        return [
            str(value)[:300]
        ]









