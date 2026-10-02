# Tender Intelligence Agent — правила для ИИ-агентов

Python-система мониторинга тендеров (ЕИС, B2B-Center, Фабрикант, РТС, ТМК, Росатом) → Telegram, Excel, SQLite, CRM-доска. Владелец проекта не программист: объясняй просто, по-русски, коротко.

## Setup
- ОС Windows, PowerShell. Python из `.venv` основной папки проекта. Перед тестами: `$env:PYTHONPATH="."`.
- Структура: `src/collectors/` (сборщики площадок), `src/orchestrator.py` (пайплайн), `src/notifications/` (Telegram, email), `src/export/excel.py`, `src/storage/` (SQLite), `src/crm/`, `src/risk/`, `src/ai/` (Ollama qwen3:8b), `tests/`.
- Перед началом работы: `git branch --show-current`, `git status`. Работай только в своей ветке.

## Build
- Тесты: `python -m pytest tests -q` и `python -m unittest discover -s tests`. Сейчас 230 тестов; на этом компьютере 1 тест (`test_eis_reliable_adapter_fails_closed_on_transport_error`) падает и без твоих правок — это сеть, не твоя ошибка.
- Каждая правка = регрессионный тест. Тесты не ослаблять и не удалять. Не объявляй задачу готовой, пока тесты не запущены.
- Коммиты маленькие, с префиксом агента: `kilo:`, `sidecar:`, `cline:`.

## Conventions
- Разделение файлов по веткам. `ai/kilo-*`: b2b_center*, eis_*. `ai/sidecar-*`: fabrikant*, browser_public*, rosatom, tenderguru. `ai/cline-*`: telegram*, notifications, export/excel, storage, crm, risk, scheduler. Чужие файлы не менять — описать проблему в `docs/agent_reports/<имя>.md`.
- Общие файлы (`orchestrator.py`, `collectors/base.py`, `collectors/registry.py`, `models/tender.py`) трогает только интегратор (ветка `integration/ai-merge`).
- Все тексты для пользователя в Telegram, Excel, логах для владельца — на русском.
- Никаких заглушек и выдуманных данных: нет значения в источнике → пустое поле. Площадка берётся из `tender.platform`, не угадывается по URL.
- Схема SQLite меняется только добавлением (новые таблицы), старые не менять.
- Цены хранить как `float`. Даты нормализуются в UTC.

## Safety
- Запрещено: `git push --force`, `git reset --hard`, `git clean`, `git rebase`, переписывание истории, push в `main`.
- Не читать и не печатать токены, пароли, `.env`, ключи. Не коммитить `.env`, `*.log`, `output/`, базы `*.sqlite3`.
- Не добавлять файлы через `git add .` — только конкретные файлы.
- Перед массовым удалением или переименованием спроси владельца.
- Если задача неясна или тесты падают по непонятной причине — остановись и опиши проблему, не угадывай.
