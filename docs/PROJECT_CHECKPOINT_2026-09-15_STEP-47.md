# Контрольная точка проекта — STEP-47

Дата: 15.09.2026

## Рабочая цепочка
- runtime fix: ce1615f7daf0ef75d39124e4fd9be09c1ebd9754
- regression tests: 3bc8c7cb02f1522eca4e9632ed2fbe4ce9517d70
- текущий main на момент checkpoint: 3bc8c7cb02f1522eca4e9632ed2fbe4ce9517d70

## Дефект
CriteriaStore.set_user_id() был no-op. Это противоречило требованию явного user context для legacy/single-user совместимости.

## Исправление
CriteriaStore теперь хранит явный _current_user_id.
set_user_id() нормализует идентификатор и задаёт контекст для методов, которым user_id не передан. Stack inspection и скрытое определение пользователя не используются.
Multi-user код продолжает передавать user_id явно.

Добавлены regression tests:
- set_user_id("user-42") используется последующими вызовами без user_id;
- default и user-42 изолированы;
- blank user id нормализуется в default.

## Проверка
Tender Intelligence Agent CI #682 — SUCCESS.
Platform Browser Diagnostics #428 — SUCCESS.
Platform Browser Diagnostics (Windows) #16 — SUCCESS.

CI #682 прошёл unittest, B2B parser, B2B reliable adapter, B2B quality gate, full pytest, search pipeline regression, analytics, SQLite/Excel integration, Excel artifact и final quality gate.

Browser #428 прошёл probe supported public portals, diagnostics artifact validation и upload.
Windows #16 — успешная runtime/browser проверка после runtime fix ce1615f7.

## Постоянный алгоритм
HEAD/checkpoint → collectors/discovery → detail contract/normalization → filters/criteria → dedup/storage/notification fingerprints → AI/Ollama → Telegram/notifications → CRM/workflow → Excel → scheduler/orchestrator/CLI → полный CI → Linux browser → Windows browser после runtime-изменений → анализ artifacts.

Любой внутренний failure:
1. найти первопричину;
2. исправить код;
3. добавить regression test;
4. повторить полный CI;
5. повторить затронутые browser/live проверки;
6. только после GREEN фиксировать checkpoint.

WAF/timeout/CAPTCHA/access block не считать успешным пустым поиском и не маскировать под code-level success.

## Итог
STEP-47 GREEN: исправленный user context, regression tests, CI, Linux browser diagnostics и Windows runtime/browser validation.
