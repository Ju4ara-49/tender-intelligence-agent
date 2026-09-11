"""UI для сохранённых поисковых профилей ("Ключей") в Telegram.

Модуль устанавливает небольшой слой над существующим Telegram runtime, не меняя
его polling и многопользовательскую изоляцию. Вся работа с профилями идёт через
SearchProfileStore и всегда ограничена chat_id текущего пользователя.
"""
from __future__ import annotations

import html
import logging
from dataclasses import asdict

from src.profiles import SearchProfile, SearchProfileStore

logger = logging.getLogger(__name__)

BTN_PROFILES = "🔑 Ключи"
BTN_PROFILE_BACK = "↩️ Назад к ключам"


def _store(bot) -> SearchProfileStore:
    store = getattr(bot, "_profile_store", None)
    if store is None:
        store = SearchProfileStore(bot.orchestrator.db)
        bot._profile_store = store
    return store


def _profile_keyboard(profiles: list[SearchProfile]) -> dict:
    rows = []
    for profile in profiles:
        mark = "☑" if profile.enabled else "☐"
        rows.append([{"text": f"{mark} {profile.name}", "callback_data": f"profile:view:{profile.id}"}])
    rows.append([{"text": "➕ Создать из текущих критериев", "callback_data": "profile:create"}])
    return {"inline_keyboard": rows}


def _detail_keyboard(profile: SearchProfile) -> dict:
    enabled_text = "⏸ Отключить" if profile.enabled else "▶️ Включить"
    return {
        "inline_keyboard": [
            [{"text": enabled_text, "callback_data": f"profile:toggle:{profile.id}"}],
            [{"text": "📊 Статистика", "callback_data": f"profile:stats:{profile.id}"}],
            [{"text": "📋 Сделать копию", "callback_data": f"profile:duplicate:{profile.id}"}],
            [{"text": "🗑 Удалить", "callback_data": f"profile:delete:{profile.id}"}],
            [{"text": BTN_PROFILE_BACK, "callback_data": "profile:list"}],
        ]
    }


def _format_profile(profile: SearchProfile) -> str:
    def money(value):
        if value is None:
            return "не задано"
        return f"{value:,.0f}".replace(",", " ")

    keywords = ", ".join(profile.keywords) if profile.keywords else "из текущих настроек"
    exclusions = ", ".join(profile.exclusions) if profile.exclusions else "нет"
    platforms = ", ".join(profile.platforms) if profile.platforms else "все доступные"
    regions = ", ".join(profile.regions) if profile.regions else "все"
    return (
        f"<b>🔑 {html.escape(profile.name)}</b>\n\n"
        f"Статус: {'включён' if profile.enabled else 'выключен'}\n"
        f"Ключевые слова: {html.escape(keywords)}\n"
        f"Исключения: {html.escape(exclusions)}\n"
        f"Площадки: {html.escape(platforms)}\n"
        f"Регионы: {html.escape(regions)}\n"
        f"Цена: {money(profile.min_price)} — {money(profile.max_price)} ₽\n"
        f"Аванс: {'требуется' if profile.advance_required else 'не обязателен'}\n"
        f"Постоплата: до {profile.max_postpayment_days} дн." if profile.max_postpayment_days is not None else
        f"Постоплата: без ограничения\n"
    ) + (
        f"Обеспечение заявки: {profile.min_application_security_percent:g}–{profile.max_application_security_percent:g}%\n"
        if profile.max_application_security_percent is not None else
        f"Обеспечение заявки: от {profile.min_application_security_percent:g}%\n"
    ) + (
        f"Минимум до дедлайна: {profile.min_submission_days} дн.\n"
        f"Минимальный AI-балл: {profile.min_ai_score}"
    )


def _show_profiles(bot, chat_id: str) -> None:
    store = _store(bot)
    profiles = store.list(chat_id)
    if not profiles:
        store.ensure_default_profile(chat_id, bot.criteria_store)
        profiles = store.list(chat_id)
    if not profiles:
        bot._send(chat_id, "<b>🔑 Ключи</b>\n\nПока нет сохранённых профилей.", bot._keyboard())
        return
    lines = ["<b>🔑 Сохранённые ключи</b>", "", "Выберите профиль для просмотра и управления.", ""]
    for profile in profiles:
        lines.append(f"{'☑' if profile.enabled else '☐'} <b>{html.escape(profile.name)}</b>")
    bot._send(chat_id, "\n".join(lines), _profile_keyboard(profiles))


def _create_from_current(bot, chat_id: str) -> None:
    store = _store(bot)
    criteria = bot.criteria_store.get(chat_id)
    keywords = bot.criteria_store.get_keywords(chat_id)
    platforms = bot.criteria_store.get_enabled_platforms(chat_id)
    existing = {p.name.lower() for p in store.list(chat_id)}
    base = "Ключ"
    name = base
    index = 2
    while name.lower() in existing:
        name = f"{base} {index}"
        index += 1
    profile = SearchProfile(
        user_id=chat_id,
        name=name,
        keywords=keywords,
        platforms=platforms,
        **asdict(criteria),
    )
    store.create(chat_id, profile)
    bot._send(chat_id, f"✅ <b>Сохранён новый ключ:</b> {html.escape(name)}", bot._keyboard())
    _show_profiles(bot, chat_id)


def _show_profile(bot, chat_id: str, profile_id: int) -> None:
    profile = _store(bot).get(chat_id, profile_id)
    if profile is None:
        bot._send(chat_id, "Профиль не найден или недоступен.", bot._keyboard())
        return
    bot._send(chat_id, _format_profile(profile), _detail_keyboard(profile))


def _show_stats(bot, chat_id: str, profile_id: int) -> None:
    store = _store(bot)
    profile = store.get(chat_id, profile_id)
    if profile is None:
        bot._send(chat_id, "Профиль не найден или недоступен.", bot._keyboard())
        return
    stats = store.stats(chat_id, profile_id)
    last = html.escape(str(stats.get("last_run_at") or "ещё не запускался"))
    text = (
        f"<b>📊 Статистика: {html.escape(profile.name)}</b>\n\n"
        f"Запусков: {stats['runs']}\n"
        f"Найдено: {stats['found']}\n"
        f"После фильтра: {stats['filtered']}\n"
        f"Новых: {stats['new_count']}\n"
        f"Проанализировано AI: {stats['analyzed']}\n"
        f"Уведомлений: {stats['notified']}\n"
        f"Дублей: {stats['duplicates']}\n"
        f"Исключено критериями: {stats['excluded_by_criteria']}\n"
        f"Последний запуск: {last}"
    )
    bot._send(chat_id, text, {"inline_keyboard": [[{"text": BTN_PROFILE_BACK, "callback_data": f"profile:view:{profile_id}"}]]})


def _duplicate_profile(bot, chat_id: str, profile_id: int) -> None:
    store = _store(bot)
    source = store.get(chat_id, profile_id)
    if source is None:
        bot._send(chat_id, "Профиль не найден или недоступен.", bot._keyboard())
        return
    existing = {p.name.lower() for p in store.list(chat_id)}
    name = f"{source.name} копия"
    index = 2
    while name.lower() in existing:
        name = f"{source.name} копия {index}"
        index += 1
    store.duplicate(chat_id, profile_id, name)
    bot._send(chat_id, f"✅ Создана копия: <b>{html.escape(name)}</b>", bot._keyboard())
    _show_profiles(bot, chat_id)


def _toggle_profile(bot, chat_id: str, profile_id: int) -> None:
    profile = _store(bot).get(chat_id, profile_id)
    if profile is None:
        bot._send(chat_id, "Профиль не найден или недоступен.", bot._keyboard())
        return
    updated = _store(bot).set_enabled(chat_id, profile_id, not profile.enabled)
    _show_profile(bot, chat_id, updated.id)


def _delete_profile(bot, chat_id: str, profile_id: int) -> None:
    store = _store(bot)
    profile = store.get(chat_id, profile_id)
    if profile is None:
        bot._send(chat_id, "Профиль не найден или недоступен.", bot._keyboard())
        return
    profiles = store.list(chat_id)
    if len(profiles) <= 1:
        bot._send(chat_id, "Нельзя удалить последний ключ. Оставьте хотя бы один профиль.", bot._keyboard())
        return
    store.delete(chat_id, profile_id)
    bot._send(chat_id, f"🗑 Ключ <b>{html.escape(profile.name)}</b> удалён.", bot._keyboard())
    _show_profiles(bot, chat_id)


def install(bot_class) -> None:
    """Добавить обработчики профилей к конкретному Telegram runtime-классу."""
    if getattr(bot_class, "_profiles_ui_installed", False):
        return
    original_keyboard = bot_class._keyboard
    original_message = bot_class._handle_message
    original_callback = bot_class._handle_callback

    def keyboard_with_profiles():
        keyboard = original_keyboard()
        rows = list(keyboard.get("keyboard", []))
        if not any(row and row[0].get("text") == BTN_PROFILES for row in rows):
            rows.insert(0, [{"text": BTN_PROFILES}])
        keyboard["keyboard"] = rows
        return keyboard

    def handle_message(self, message):
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if chat_id and text == BTN_PROFILES:
            _show_profiles(self, chat_id)
            return
        original_message(self, message)

    def handle_callback(self, callback):
        data = str(callback.get("data", ""))
        message = callback.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        if not data.startswith("profile:"):
            original_callback(self, callback)
            return
        callback_id = str(callback.get("id", ""))
        self._answer_callback(callback_id)
        try:
            parts = data.split(":")
            action = parts[1] if len(parts) > 1 else "list"
            profile_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
            if action == "list":
                _show_profiles(self, chat_id)
            elif action == "create":
                _create_from_current(self, chat_id)
            elif profile_id is None:
                self._send(chat_id, "Некорректный идентификатор профиля.", self._keyboard())
            elif action == "view":
                _show_profile(self, chat_id, profile_id)
            elif action == "stats":
                _show_stats(self, chat_id, profile_id)
            elif action == "toggle":
                _toggle_profile(self, chat_id, profile_id)
            elif action == "duplicate":
                _duplicate_profile(self, chat_id, profile_id)
            elif action == "delete":
                _delete_profile(self, chat_id, profile_id)
            else:
                self._send(chat_id, "Неизвестная операция с ключом.", self._keyboard())
        except Exception:
            logger.exception("Telegram-профили: ошибка callback=%s chat_id=%s", data, chat_id)
            self._send(chat_id, "Не удалось обработать операцию с ключом.", self._keyboard())

    bot_class._keyboard = staticmethod(keyboard_with_profiles)
    bot_class._handle_message = handle_message
    bot_class._handle_callback = handle_callback
    bot_class._profiles_ui_installed = True
