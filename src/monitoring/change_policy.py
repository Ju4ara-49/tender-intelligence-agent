"""Классификация значимых изменений тендера.

Модуль намеренно не отправляет уведомления сам. Он превращает сырой diff
snapshot-ов в детерминированное событие, которое можно безопасно дедуплицировать
и отправить через любой канал.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

IMPORTANT_FIELDS = frozenset({
    "price", "deadline", "description", "raw_data", "title", "customer",
    "application_security", "contract_security", "advance_payment",
    "postpayment", "documents", "law_type", "region",
})

FIELD_CATEGORY = {
    "price": "Цена",
    "deadline": "Срок подачи",
    "description": "Описание",
    "raw_data": "Документация/условия",
    "title": "Название",
    "customer": "Заказчик",
    "application_security": "Обеспечение заявки",
    "contract_security": "Обеспечение контракта",
    "advance_payment": "Аванс",
    "postpayment": "Условия оплаты",
    "documents": "Документы",
    "law_type": "Закон/режим закупки",
    "region": "Регион",
}

@dataclass(frozen=True)
class ChangeDecision:
    significant: bool
    categories: tuple[str, ...]
    fields: tuple[str, ...]

def classify_changed_fields(fields: Iterable[str]) -> ChangeDecision:
    categories: list[str] = []
    selected: list[str] = []
    seen_categories: set[str] = set()
    for field in fields:
        key = str(field or "").strip()
        if key not in IMPORTANT_FIELDS:
            continue
        selected.append(key)
        category = FIELD_CATEGORY[key]
        if category not in seen_categories:
            seen_categories.add(category)
            categories.append(category)
    return ChangeDecision(bool(selected), tuple(categories), tuple(selected))

def significant_diff(previous: Mapping[str, Any], current: Mapping[str, Any]) -> ChangeDecision:
    """Сравнить два snapshot без зависимости от порядка ключей."""
    fields = []
    for field in IMPORTANT_FIELDS:
        if previous.get(field) != current.get(field):
            fields.append(field)
    # Preserve a stable presentation order rather than set iteration order.
    ordered = [f for f in FIELD_CATEGORY if f in fields]
    return classify_changed_fields(ordered)
