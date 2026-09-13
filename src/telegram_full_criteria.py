"""Telegram UI for the complete per-user tender criteria set."""
from __future__ import annotations

import html
import logging
import time

from src.crm.telegram import handle_callback as handle_crm_callback
from src.crm.telegram import handle_message as handle_crm_message
from src.profiles import SearchProfile
from src.telegram_criteria_multiuser import CriteriaAwareResponsiveTelegramBot
from src.telegram_bot import PLATFORM_NAMES

BTN_REGIONS = "Регионы"
BTN_EXCLUDE = "Исключить слова"
BTN_PROFILES = "Ключи"
BTN_CRM = "CRM тендера"

_PROFILE_FIELD_LABELS = {
    "name": "Название", "keywords": "Ключевые слова", "exclusions": "Исключающие слова",
    "platforms": "Площадки", "regions": "Регионы", "min_price": "Цена от", "max_price": "Цена до",
    "min_advance_percent": "Аванс от", "max_postpayment_days": "Постоплата до",
    "min_application_security_percent": "Обеспечение заявки от",
    "max_application_security_percent": "Обеспечение заявки до",
    "min_contract_security_percent": "Обеспечение контракта от",
    "max_contract_security_percent": "Обеспечение контракта до",
    "min_submission_days": "Срок до подачи от", "min_ai_score": "Минимальный AI балл",
}

_PROFILE_NUMERIC_FIELDS = {
    "min_price": (float, 0, None), "max_price": (float, 0, None),
    "min_advance_percent": (float, 0, 100), "max_postpayment_days": (int, 0, 3650),
    "min_application_security_percent": (float, 0, 100), "max_application_security_percent": (float, 0, 100),
    "min_contract_security_percent": (float, 0, 100), "max_contract_security_percent": (float, 0, 100),
    "min_submission_days": (int, 0, 3650), "min_ai_score": (int, 0, 100),
}
_PROFILE_LIST_FIELDS = {"keywords", "exclusions", "platforms", "regions"}
_CLEAR_VALUES = {"нет", "none", "off", "сброс", "сбросить"}


class FullCriteriaTelegramBot(CriteriaAwareResponsiveTelegramBot):
    """Commercial criteria plus region/exclusion/profile/CRM controls."""

    @staticmethod
    def _keyboard() -> dict:
        base = CriteriaAwareResponsiveTelegramBot._keyboard()
        keyboard = list(base["keyboard"])
        keyboard.insert(4, [{"text": BTN_REGIONS}, {"text": BTN_EXCLUDE}])
        keyboard.insert(5, [{"text": BTN_PROFILES}])
        keyboard.insert(6, [{"text": BTN_CRM}])
        base["keyboard"] = keyboard
        return base

    def _handle_message(self, message: dict) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        text = (message.get("text") or "").strip()
        if not self._is_allowed(chat_id):
            self._access_denied(chat_id)
            return
        if self._is_owner(chat_id) and (
            chat_id in self._admin_waiting or text.startswith("/admin") or text.startswith("/users")
            or text.startswith("/add_user") or text.startswith("/remove_user")
        ):
            return super()._handle_message(message)
        if text == BTN_CRM:
            self._ask_value(chat_id, "crm_tender_id", "Введите внутренний ID тендера из базы.\n\nНапример:\n<code>123</code>")
            return
        if text == BTN_PROFILES:
            self._show_profiles(chat_id)
            return
        if handle_crm_message(self, chat_id, text):
            return
        if text == BTN_REGIONS:
            self._ask_value(chat_id, "regions", "Введите регионы через запятую.\n\nНапример:\n<code>Санкт-Петербург, Ленинградская область, Москва</code>\n\n<code>нет</code> = все регионы.")
            return
        if text == BTN_EXCLUDE:
            self._ask_value(chat_id, "exclude_keywords", "Введите слова для исключения через запятую.\n\nНапример:\n<code>строительство, ремонт, продукты</code>\n\n<code>нет</code> = отключить пользовательские исключения.")
            return
        super()._handle_message(message)

    def _handle_callback(self, callback: dict) -> None:
        data = str(callback.get("data", ""))
        message = callback.get("message") or {}
        chat_id = str(message.get("chat", {}).get("id", ""))
        callback_id = str(callback.get("id", ""))
        if chat_id and not self._is_allowed(chat_id):
            self._answer_callback(callback_id)
            self._access_denied(chat_id)
            return
        if data.startswith("profiles:"):
            self._answer_callback(callback_id)
            try:
                self._handle_profile_callback(chat_id, data)
            except Exception:
                logging.getLogger(__name__).exception("Telegram: ошибка profile callback=%s", data)
                self._send(chat_id, "❌ Ошибка управления профилем. Подробности в logs/agent.log.", self._keyboard())
            return
        if chat_id and handle_crm_callback(self, chat_id, data):
            self._answer_callback(callback_id)
            return
        super()._handle_callback(callback)

    def _handle_value_input(self, chat_id: str, text: str) -> bool:
        field = self._waiting_for.get(chat_id)
        if field == "crm_tender_id":
            self._waiting_for.pop(chat_id, None)
            if not text.strip().isdigit() or int(text.strip()) <= 0:
                self._send(chat_id, "ID тендера должен быть положительным целым числом.", self._keyboard())
                return True
            handle_crm_message(self, chat_id, f"/tender {int(text.strip())}")
            return True
        if field == "profile_create_name":
            return self._handle_profile_create(chat_id, text)
        if field and field.startswith("profile_duplicate_name:"):
            return self._handle_profile_duplicate(chat_id, text)
        if field and field.startswith("profile:"):
            return self._handle_profile_value(chat_id, text)
        if field not in {"regions", "exclude_keywords"}:
            return super()._handle_value_input(chat_id, text)
        raw = text.strip()
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        values = [] if raw.casefold() in _CLEAR_VALUES else [x.strip() for x in raw.split(",") if x.strip()]
        if field == "regions":
            self.criteria_store.set_regions(chat_id, values)
            label = "Регионы"
        else:
            self.criteria_store.set_exclude_keywords(chat_id, values)
            label = "Исключающие слова"
        self._waiting_for.pop(chat_id, None)
        value_text = ", ".join(values) if values else "не задано"
        self._send(chat_id, f"<b>{label}:</b> {html.escape(value_text)}\n\nКритерий сохранён.", self._keyboard())
        return True

    # -------------------------- Saved Search Profiles -------------------------
    def _show_profiles(self, chat_id: str) -> None:
        profiles = self.orchestrator.profile_store.list(chat_id)
        if not profiles:
            self._send(chat_id, "<b>Ключи поиска</b>\n\nПрофилей пока нет. Создайте первый профиль — он будет заполнен текущими критериями.", self._profiles_keyboard([]))
            return
        lines = ["<b>Ключи поиска</b>", "", "В поиск попадают все включённые профили.", ""]
        for profile in profiles:
            state = "включён" if profile.enabled else "выключен"
            stats = self.orchestrator.profile_store.stats(chat_id, int(profile.id or 0))
            lines.append(f"• <b>{html.escape(profile.name)}</b> — {state}; запусков: {int(stats.get('runs') or 0)}")
        self._send(chat_id, "\n".join(lines), self._profiles_keyboard(profiles))

    @staticmethod
    def _profiles_keyboard(profiles: list[SearchProfile]) -> dict:
        rows = [[{"text": "➕ Создать профиль", "callback_data": "profiles:create"}]]
        for profile in profiles:
            pid = int(profile.id or 0)
            mark = "☑" if profile.enabled else "☐"
            rows.append([{"text": f"{mark} {profile.name[:28]}", "callback_data": f"profiles:open:{pid}"}])
        rows.append([{"text": "Закрыть", "callback_data": "profiles:close"}])
        return {"inline_keyboard": rows}

    @staticmethod
    def _profile_edit_keyboard(profile_id: int) -> dict:
        fields = [
            ("name", "Название"), ("keywords", "Ключевые слова"), ("exclusions", "Исключения"),
            ("advance_required", "Аванс обязателен"),
            ("platforms", "Площадки"), ("regions", "Регионы"), ("min_price", "Цена от"),
            ("max_price", "Цена до"), ("min_advance_percent", "Аванс от"),
            ("max_postpayment_days", "Постоплата до"), ("min_application_security_percent", "Заявка от"),
            ("max_application_security_percent", "Заявка до"), ("min_contract_security_percent", "Контракт от"),
            ("max_contract_security_percent", "Контракт до"), ("min_submission_days", "Дней до подачи"),
            ("min_ai_score", "AI балл"),
        ]
        rows = []
        for i in range(0, len(fields), 2):
            rows.append([{"text": label, "callback_data": f"profiles:edit:{profile_id}:{field}"} for field, label in fields[i:i + 2]])
        rows += [
            [{"text": "💰 Аванс обязателен: переключить", "callback_data": f"profiles:advance:{profile_id}"}],
            [{"text": "☑/☐ Включить/выключить", "callback_data": f"profiles:toggle:{profile_id}"}],
            [{"text": "📋 Дублировать", "callback_data": f"profiles:duplicate:{profile_id}"}],
            [{"text": "🗑 Удалить", "callback_data": f"profiles:delete:{profile_id}"}],
            [{"text": "⬅️ К списку", "callback_data": "profiles:list"}],
        ]
        return {"inline_keyboard": rows}

    def _profile_detail(self, chat_id: str, profile_id: int) -> None:
        profile = self.orchestrator.profile_store.get(chat_id, profile_id)
        if profile is None:
            self._send(chat_id, "Профиль не найден или принадлежит другому пользователю.", self._profiles_keyboard([]))
            return
        stats = self.orchestrator.profile_store.stats(chat_id, profile_id)
        lines = [
            f"<b>Ключ: {html.escape(profile.name)}</b>",
            f"Статус: {'включён' if profile.enabled else 'выключен'}",
            f"Ключевые слова: {html.escape(', '.join(profile.keywords) or 'из общих настроек')}",
            f"Исключения: {html.escape(', '.join(profile.exclusions) or 'нет')}",
            f"Площадки: {html.escape(', '.join(self._platform_name(p) for p in profile.platforms) or 'все разрешённые')}",
            f"Регионы: {html.escape(', '.join(profile.regions) or 'все')}",
            f"Цена: {self._fmt(profile.min_price)} — {self._fmt(profile.max_price)}",
            f"Аванс: {("обязателен" if profile.advance_required else "не обязателен")}; от {self._fmt(profile.min_advance_percent)}%",
            f"Постоплата до: {self._fmt(profile.max_postpayment_days)} дн.",
            f"Обеспечение заявки: {self._fmt(profile.min_application_security_percent)}–{self._fmt(profile.max_application_security_percent)}%",
            f"Обеспечение контракта: {self._fmt(profile.min_contract_security_percent)}–{self._fmt(profile.max_contract_security_percent)}%",
            f"Дней до подачи: {profile.min_submission_days}", f"AI балл: {profile.min_ai_score}", "",
            f"Запусков: {int(stats.get('runs') or 0)}; найдено: {int(stats.get('found') or 0)}; уведомлений: {int(stats.get('notified') or 0)}",
        ]
        self._send(chat_id, "\n".join(lines), self._profile_edit_keyboard(profile_id))

    @staticmethod
    def _fmt(value) -> str:
        if value is None:
            return "не задано"
        number = float(value)
        return str(int(number)) if number.is_integer() else f"{number:g}"

    def _handle_profile_callback(self, chat_id: str, data: str) -> None:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if action == "list":
            self._show_profiles(chat_id)
            return
        if action == "close":
            self._send(chat_id, "Управление ключами закрыто.", self._keyboard())
            return
        if action == "create":
            self._ask_value(chat_id, "profile_create_name", "Введите название нового ключа поиска.\n\nНапример: <code>Подшипники СПб</code>")
            return
        if len(parts) < 3 or not parts[2].isdigit():
            self._send(chat_id, "Некорректный ID профиля.", self._keyboard())
            return
        profile_id = int(parts[2])
        profile = self.orchestrator.profile_store.get(chat_id, profile_id)
        if profile is None:
            self._send(chat_id, "Профиль не найден.", self._profiles_keyboard([]))
            return
        if action == "open":
            self._profile_detail(chat_id, profile_id)
        elif action == "advance":
            self.orchestrator.profile_store.update(chat_id, profile_id, advance_required=not profile.advance_required)
            self._profile_detail(chat_id, profile_id)
        elif action == "toggle":
            self.orchestrator.profile_store.set_enabled(chat_id, profile_id, not profile.enabled)
            self._show_profiles(chat_id)
        elif action == "delete":
            self.orchestrator.profile_store.delete(chat_id, profile_id)
            self._show_profiles(chat_id)
        elif action == "duplicate":
            self._ask_value(chat_id, f"profile_duplicate_name:{profile_id}", f"Введите название копии профиля <b>{html.escape(profile.name)}</b>.")
        elif action == "edit" and len(parts) == 4:
            field = parts[3]
            if field == "advance_required":
                self.orchestrator.profile_store.update(chat_id, profile_id, advance_required=not profile.advance_required)
                self._profile_detail(chat_id, profile_id)
                return
            if field not in _PROFILE_FIELD_LABELS:
                self._send(chat_id, "Неизвестное поле профиля.", self._profile_edit_keyboard(profile_id))
                return
            self._ask_value(chat_id, f"profile:{profile_id}:{field}", self._profile_prompt(profile, field))
        else:
            self._send(chat_id, "Неизвестная операция с профилем.", self._profile_edit_keyboard(profile_id))

    def _profile_prompt(self, profile: SearchProfile, field: str) -> str:
        label = _PROFILE_FIELD_LABELS[field]
        current = getattr(profile, field)
        if field in _PROFILE_LIST_FIELDS:
            current_text, hint = ", ".join(str(x) for x in current) if current else "нет", "через запятую; «нет» = очистить"
        elif field == "name":
            current_text, hint = str(current), "название не должно быть пустым"
        else:
            current_text = self._fmt(current)
            hint = "«нет» = отключить ограничение" if field not in {"min_submission_days", "min_ai_score"} else "целое число"
        return f"<b>{label}</b>\nТекущее значение: <code>{html.escape(current_text)}</code>\n\nВведите новое значение ({hint})."

    def _handle_profile_create(self, chat_id: str, text: str) -> bool:
        name = text.strip()
        if not name:
            self._send(chat_id, "Название не может быть пустым. Введите его ещё раз.", self._keyboard())
            return True
        criteria = self.criteria_store.get(chat_id)
        profile = SearchProfile(
            user_id=chat_id, name=name, keywords=self.criteria_store.get_keywords(chat_id),
            exclusions=self.criteria_store.get_exclude_keywords(chat_id), platforms=self.criteria_store.get_enabled_platforms(chat_id),
            regions=self.criteria_store.get_regions(chat_id), min_price=criteria.min_price, max_price=criteria.max_price,
            advance_required=criteria.advance_required, min_advance_percent=criteria.min_advance_percent,
            max_postpayment_days=criteria.max_postpayment_days, min_submission_days=criteria.min_submission_days,
            min_application_security_percent=criteria.min_application_security_percent,
            max_application_security_percent=criteria.max_application_security_percent,
            min_contract_security_percent=criteria.min_contract_security_percent,
            max_contract_security_percent=criteria.max_contract_security_percent, min_ai_score=criteria.min_ai_score,
        )
        try:
            created = self.orchestrator.profile_store.create(chat_id, profile)
        except Exception as exc:
            self._send(chat_id, f"❌ Не удалось создать профиль: {html.escape(str(exc))}", self._profiles_keyboard(self.orchestrator.profile_store.list(chat_id)))
            return True
        self._waiting_for.pop(chat_id, None)
        self._profile_detail(chat_id, int(created.id))
        return True

    def _handle_profile_duplicate(self, chat_id: str, text: str) -> bool:
        field = self._waiting_for.get(chat_id, "")
        try:
            profile_id = int(field.split(":", 1)[1])
            name = text.strip()
            if not name:
                raise ValueError("название не может быть пустым")
            created = self.orchestrator.profile_store.duplicate(chat_id, profile_id, name)
        except Exception as exc:
            self._send(chat_id, f"❌ Не удалось создать копию: {html.escape(str(exc))}", self._profiles_keyboard(self.orchestrator.profile_store.list(chat_id)))
            return True
        self._waiting_for.pop(chat_id, None)
        self._profile_detail(chat_id, int(created.id))
        return True

    def _handle_profile_value(self, chat_id: str, text: str) -> bool:
        field = self._waiting_for.get(chat_id, "")
        _, profile_id_text, target = field.split(":", 2)
        if not profile_id_text.isdigit():
            self._waiting_for.pop(chat_id, None)
            return True
        profile_id = int(profile_id_text)
        profile = self.orchestrator.profile_store.get(chat_id, profile_id)
        if profile is None:
            self._waiting_for.pop(chat_id, None)
            self._send(chat_id, "Профиль не найден.", self._profiles_keyboard([]))
            return True
        raw = text.strip()
        if ":" in raw:
            raw = raw.split(":", 1)[1].strip()
        try:
            if target == "advance_required":
                raise ValueError("для этого поля используйте кнопку переключения")
            if target == "name":
                value = raw
                if not value:
                    raise ValueError("название не может быть пустым")
            elif target in _PROFILE_LIST_FIELDS:
                value = [] if raw.casefold() in _CLEAR_VALUES else [x.strip() for x in raw.split(",") if x.strip()]
                if target == "platforms":
                    reverse = {name.casefold(): key for key, name in PLATFORM_NAMES.items()}
                    normalized = []
                    for item in value:
                        key = reverse.get(item.casefold(), item.strip())
                        if key not in PLATFORM_NAMES:
                            raise ValueError(f"неизвестная площадка: {item}")
                        if key not in normalized:
                            normalized.append(key)
                    value = normalized
            else:
                caster, minimum, maximum = _PROFILE_NUMERIC_FIELDS[target]
                if raw.casefold() in _CLEAR_VALUES and target not in {"min_submission_days", "min_ai_score"}:
                    value = None
                else:
                    value = caster(raw.replace(" ", "").replace(",", "."))
                    if value < minimum or (maximum is not None and value > maximum):
                        raise ValueError("значение вне допустимого диапазона")
        except (TypeError, ValueError) as exc:
            self._send(chat_id, f"❌ Некорректное значение: {html.escape(str(exc))}. Попробуйте ещё раз.", self._profile_edit_keyboard(profile_id))
            return True
        values = {target: value}
        if target == "min_advance_percent":
            values["advance_required"] = value is not None and value > 0
        try:
            self.orchestrator.profile_store.update(chat_id, profile_id, **values)
        except Exception as exc:
            self._send(chat_id, f"❌ Не удалось сохранить: {html.escape(str(exc))}", self._profile_edit_keyboard(profile_id))
            return True
        self._waiting_for.pop(chat_id, None)
        self._profile_detail(chat_id, profile_id)
        return True

    # -------------------------- Existing criteria UI --------------------------
    def _cmd_settings(self, chat_id: str) -> None:
        super()._cmd_settings(chat_id)
        regions = self.criteria_store.get_regions(chat_id)
        exclusions = self.criteria_store.get_exclude_keywords(chat_id)
        text = (
            "<b>Дополнительные критерии</b>\n\n"
            f"Регионы: {html.escape(', '.join(regions) if regions else 'все')}\n"
            f"Исключающие слова: {html.escape(', '.join(exclusions) if exclusions else 'не заданы')}"
        )
        self._send(chat_id, text, self._keyboard())

    def _cmd_reset(self, chat_id: str) -> None:
        super()._cmd_reset(chat_id)
        self.criteria_store.set_regions(chat_id, [])
        self.criteria_store.set_exclude_keywords(chat_id, [])

    def _run_search_for_user(self, chat_id: str, orchestrator) -> None:
        started_at = time.monotonic()
        self._send(chat_id, "🔄 <b>Поиск выполняется...</b>\n\nИдёт сбор и анализ тендеров.", self._keyboard())
        try:
            profile_results = orchestrator.run_cycle_for_user(chat_id)
            stats = self._aggregate_profile_stats(profile_results)
            self._send_search_results(chat_id, orchestrator)
            elapsed = int(time.monotonic() - started_at)
            elapsed_text = f"{elapsed // 60} мин. {elapsed % 60:02d} сек." if elapsed >= 60 else f"{elapsed} сек."
            state = "остановлен" if orchestrator.stop_requested else "завершён"
            text = (
                f"{'⛔' if orchestrator.stop_requested else '✅'} <b>Поиск профилей {state}.</b>\n\n"
                f"Профилей запущено: {len(profile_results)}\nВремя: {elapsed_text}\n"
                f"Найдено: {stats['found']}\nПрошло фильтр: {stats['filtered']}\nНовых: {stats['new']}\n"
                f"AI: {stats['analyzed']}\nИсключено: {stats['excluded_by_criteria']}\n"
                f"Уведомлений: {stats['notified']}\nДублей: {stats['skipped_duplicate']}\n\n"
                "📊 <b>Результаты сохранены в Excel.</b>"
            )
            self._send(chat_id, text, self._keyboard())
        except Exception:
            logging.getLogger(__name__).exception("Telegram-бот: ошибка выполнения расширенного поиска для chat_id=%s", chat_id)
            self._send(chat_id, "❌ <b>Ошибка поиска.</b>\n\nПодробности находятся в logs/agent.log.", self._keyboard())
        finally:
            with self._search_lock:
                self._search_threads.pop(chat_id, None)
                self._user_orchestrators.pop(chat_id, None)

    @staticmethod
    def _aggregate_profile_stats(results: list[dict[str, int]]) -> dict[str, int]:
        keys = ("found", "filtered", "new", "analyzed", "notified", "skipped_duplicate", "excluded_by_criteria", "details_loaded", "details_partial", "details_failed", "saved", "ai_failed")
        return {key: sum(int(result.get(key, 0) or 0) for result in results) for key in keys}

    def _send_search_results(self, chat_id: str, orchestrator) -> None:
        results = orchestrator.last_run_results
        if not results:
            self._send(chat_id, "📭 <b>По результатам поиска подходящих тендеров нет.</b>", self._keyboard())
            return
        self._send(chat_id, f"📋 <b>Результаты поиска: {len(results)}</b>", self._keyboard())
        for index, tender in enumerate(results, 1):
            price = f"{tender.price:,.0f} {tender.currency}".replace(",", " ") if tender.price is not None else "не указана"
            published = tender.published_at or tender.start_date
            published_date = published.strftime("%d.%m.%Y") if published else "не указана"
            deadline = tender.deadline.strftime("%d.%m.%Y") if tender.deadline else "не указан"
            title = html.escape(tender.title or "Без названия")
            customer = html.escape(tender.customer or "не указан")
            region = html.escape(tender.region or "не указан")
            url = html.escape(tender.url or "")
            text = f"<b>{index}. {title}</b>\n📅 дата закупки: {published_date}\n🏢 {customer}\n📍 регион: {region}\n💰 {price}\n⏰ до {deadline}"
            if url:
                text += f'\n🔗 <a href="{url}">Открыть тендер</a>'
            self._send(chat_id, text, self._keyboard())

    @staticmethod
    def _platform_name(platform: str) -> str:
        return PLATFORM_NAMES.get(platform, platform)
