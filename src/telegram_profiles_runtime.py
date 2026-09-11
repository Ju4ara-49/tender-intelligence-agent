"""Связка сохранённых Telegram-профилей с фактическим запуском поиска."""
from __future__ import annotations

import time


AGGREGATE_KEYS = (
    "found", "soft_filtered", "filtered", "keyword_excluded", "new", "analyzed",
    "notified", "skipped_duplicate", "excluded_by_criteria", "excluded_by_region",
    "details_loaded", "details_failed",
)


def install(bot_class) -> None:
    """Переключить Telegram search runtime на все активные профили пользователя."""
    if getattr(bot_class, "_profiles_runtime_installed", False):
        return
    original = bot_class._run_search_for_user

    def run_search_for_profiles(self, chat_id: str, orchestrator) -> None:
        started_at = time.monotonic()
        self._send(chat_id, "🔄 <b>Поиск выполняется...</b>\n\nЗапускаю все включённые ключи пользователя.", self._keyboard())
        # Старый Orchestrator очищает stop-флаг в начале каждого run_cycle().
        # Для пакетного запуска нескольких ключей это опасно: нажатие «Стоп» между
        # профилями может быть потеряно. На время batch-run делаем clear безопасным no-op,
        # предварительно снимая старый флаг один раз.
        original_clear_stop = orchestrator.clear_stop_request
        original_clear_stop()
        orchestrator.clear_stop_request = lambda: None
        try:
            runs = orchestrator.run_cycle_for_user(chat_id)
            if not runs:
                original(self, chat_id, orchestrator)
                return
            aggregate = {key: 0 for key in AGGREGATE_KEYS}
            for stats in runs:
                for key in AGGREGATE_KEYS:
                    aggregate[key] += int(stats.get(key, 0))
            aggregate["search_number"] = runs[-1]["search_number"]
            if orchestrator.last_run_results:
                self._send_search_results(chat_id, orchestrator)
            elapsed = int(time.monotonic() - started_at)
            elapsed_text = f"{elapsed // 60} мин. {elapsed % 60:02d} сек." if elapsed >= 60 else f"{elapsed} сек."
            state = "остановлен" if orchestrator.stop_requested else "завершён"
            text = (
                f"{'⛔' if orchestrator.stop_requested else '✅'} <b>Поиск по ключам {state}.</b>\n\n"
                f"Активных ключей: {len(runs)}\n"
                f"Время: {elapsed_text}\n"
                f"Найдено: {aggregate['found']}\n"
                f"Прошло фильтр: {aggregate['filtered']}\n"
                f"Новых: {aggregate['new']}\n"
                f"AI: {aggregate['analyzed']}\n"
                f"Исключено: {aggregate['excluded_by_criteria']}\n"
                f"Уведомлений: {aggregate['notified']}\n"
                f"Дублей: {aggregate['skipped_duplicate']}"
            )
            self._send(chat_id, text, self._keyboard())
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Telegram-профили: ошибка запуска ключей для chat_id=%s", chat_id)
            self._send(chat_id, "❌ <b>Ошибка поиска по ключам.</b>\n\nПодробности находятся в logs/agent.log.", self._keyboard())
        finally:
            orchestrator.clear_stop_request = original_clear_stop
            with self._search_lock:
                self._search_threads.pop(chat_id, None)
                self._user_orchestrators.pop(chat_id, None)

    bot_class._run_search_for_user = run_search_for_profiles
    bot_class._profiles_runtime_installed = True
