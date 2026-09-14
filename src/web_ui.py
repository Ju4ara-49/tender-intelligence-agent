"""Локальный web-интерфейс профиля поиска тендеров."""
from __future__ import annotations
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from src.profiles import SearchProfile, SearchProfileStore
from src.settings import load_settings
from src.storage.database import TenderDatabase

PLATFORMS = [
    ("eis", "ЕИС"), ("b2b_center", "B2B-Center"), ("rts_tender", "РТС-тендер"),
    ("fabrikant", "Фабрикант"), ("tmk", "ТМК"), ("rosatom", "Росатом"),
]

def _v(form, key, default=""):
    return (form.get(key, [default])[0] or default).strip()

def _list(form, key):
    values = form.get(key, [])
    result = []
    for value in values:
        result.extend(x.strip() for x in str(value).replace("\\n", ",").split(",") if x.strip())
    return result

def _float(form, key):
    raw = _v(form, key)
    return None if not raw else float(raw.replace(" ", "").replace(",", "."))

def _int(form, key):
    raw = _v(form, key)
    return None if not raw else int(raw)

def profile_from_form(form, user_id="web-local"):
    selected = set(_list(form, "platforms"))
    return SearchProfile(
        user_id=user_id, name=_v(form, "name", "Основной"),
        keywords=_list(form, "keywords"), exclusions=_list(form, "exclusions"),
        platforms=[k for k, _ in PLATFORMS if k in selected], regions=_list(form, "regions"),
        min_price=_float(form, "min_price"), max_price=_float(form, "max_price"),
        advance_required=_v(form, "advance_required") == "1",
        min_advance_percent=float(_v(form, "min_advance_percent", "0").replace(",", ".")),
        max_postpayment_days=_int(form, "max_postpayment_days"),
        min_submission_days=int(_v(form, "min_submission_days", "7")),
        min_application_security_percent=float(_v(form, "min_application_security_percent", "0").replace(",", ".")),
        max_application_security_percent=_float(form, "max_application_security_percent"),
        min_contract_security_percent=float(_v(form, "min_contract_security_percent", "0").replace(",", ".")),
        max_contract_security_percent=_float(form, "max_contract_security_percent"),
        min_ai_score=int(_v(form, "min_ai_score", "70")),
    )

CSS = """\
:root{--navy:#304579;--blue:#248ee7;--bg:#dce4f0;--panel:#f6f8fc;--line:#afbdd2;--text:#263449}
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:var(--bg);color:var(--text)}
.top{height:70px;background:#fff;display:flex}.brand{width:250px;background:var(--navy);color:#fff;font-size:28px;padding:18px 24px}.nav{display:flex}.nav a{padding:24px 38px;color:#52719e;text-decoration:none;font-weight:600;border-right:1px solid #d5dce8}.nav .active{background:#536ba4;color:#fff}
.layout{display:grid;grid-template-columns:250px 1fr;min-height:calc(100vh - 70px)}.side{background:var(--navy);color:#fff}.notice{background:var(--blue);padding:14px 20px}.side h3{padding:20px;margin:0 0 0;font-size:17px}.item{padding:11px 20px}.selected{background:#41598e}
.main{padding:28px;max-width:1150px}.title{font-size:29px;margin:0 0 24px}.panel{background:var(--panel);border:1px solid var(--line);padding:20px 18px 24px;margin-bottom:14px}.panel h2{font-size:18px;margin:0 0 18px}.row{display:grid;grid-template-columns:165px 1fr;gap:14px;align-items:center;margin:13px 0}.label{font-weight:600}.input,.textarea{width:100%;border:1px solid #a8b8cf;background:#fff;padding:11px 13px;font-size:15px;border-radius:3px}.textarea{min-height:75px;resize:vertical}.checks{display:flex;gap:18px;flex-wrap:wrap}.check{display:inline-flex;gap:7px;align-items:center}.check input{width:18px;height:18px}.range{display:grid;grid-template-columns:1fr 1fr;gap:12px}.details{border-top:1px solid #cbd5e3;margin-top:15px;padding-top:10px}.details summary{cursor:pointer;font-weight:700;color:#45658f;padding:9px 0}.actions{display:flex;justify-content:flex-end;gap:12px}.btn{border:1px solid #93a8c5;border-radius:4px;padding:12px 28px;background:#fff;color:#526985;text-decoration:none}.primary{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:700}.toast{background:#e9f7e9;border:1px solid #98c998;padding:12px;margin-bottom:15px}
@media(max-width:800px){.brand{width:170px;font-size:22px}.nav a{padding:24px 10px}.layout{grid-template-columns:170px 1fr}.row{grid-template-columns:1fr}.range{grid-template-columns:1fr}.main{padding:18px}}
"""

def render_form(profile=None, saved=False):
    p = profile or SearchProfile()
    e = lambda x: html.escape("" if x is None else str(x))
    platforms = "".join(
        '<label class="check"><input type="checkbox" name="platforms" value="' + e(k) + '"' +
        (" checked" if k in set(p.platforms) else "") + "> " + e(n) + "</label>"
        for k,n in PLATFORMS
    )
    notice = '<div class="toast">Профиль сохранён в общей базе профилей поиска.</div>' if saved else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ТендерПлан — Добавление ключа</title><style>{CSS}</style></head>
<body><header class="top"><div class="brand">тендерплан</div><nav class="nav"><a class="active" href="/">Ключи и метки</a><a href="#">Пользователи</a><a href="#">Личные настройки</a></nav></header>
<div class="layout"><aside class="side"><div class="notice">🔔 Новых уведомлений</div><h3>Ключи</h3><div class="item selected">Все</div><div class="item">Мои ключи</div><div class="item">Активные</div><h3>Разделы</h3><div class="item">Аналитика</div><div class="item">CRM тендера</div><div class="item">Календарь</div></aside>
<main class="main"><h1 class="title">Добавление нового ключа</h1>{notice}<form method="post" action="/profiles">
<section class="panel"><h2>Поиск в названии контракта, номенклатуре и документации</h2>
<div class="row"><div class="label">Название ключа</div><input class="input" name="name" required value="{e(p.name)}" placeholder="Например, Оргтехника"></div>
<div class="row"><div class="label">Ключевые слова</div><textarea class="textarea" name="keywords" placeholder="подшипники, запчасти, оргтехника">{e(', '.join(p.keywords))}</textarea></div>
<div class="row"><div class="label">Исключая</div><textarea class="textarea" name="exclusions" placeholder="строительство, ремонт, продукты">{e(', '.join(p.exclusions))}</textarea></div>
<div class="row"><div></div><label class="check"><input type="checkbox" checked disabled> Искать внутри документации</label></div>
<div class="row"><div class="label">Регион</div><input class="input" name="regions" value="{e(', '.join(p.regions))}" placeholder="Санкт-Петербург, Ленинградская область, Москва"></div></section>
<section class="panel"><h2>Площадки</h2><div class="checks">{platforms}</div></section>
<section class="panel"><h2>Основные фильтры</h2>
<div class="row"><div class="label">Начальная цена</div><div class="range"><input class="input" name="min_price" value="{e(p.min_price)}" placeholder="от"><input class="input" name="max_price" value="{e(p.max_price)}" placeholder="до"></div></div>
<div class="row"><div class="label">Аванс</div><div><label class="check"><input type="checkbox" name="advance_required" value="1"{' checked' if p.advance_required else ''}> Аванс обязателен</label><input class="input" style="margin-top:8px" name="min_advance_percent" value="{e(p.min_advance_percent)}" placeholder="Аванс от, %"></div></div>
<div class="row"><div class="label">Постоплата</div><input class="input" name="max_postpayment_days" value="{e(p.max_postpayment_days)}" placeholder="Не более, дней"></div>
<div class="row"><div class="label">Срок до подачи</div><input class="input" name="min_submission_days" value="{e(p.min_submission_days)}" placeholder="Не менее 7 дней"></div>
<div class="details"><details open><summary>Размер обеспечения заявки</summary><div class="range"><input class="input" name="min_application_security_percent" value="{e(p.min_application_security_percent)}" placeholder="от, %"><input class="input" name="max_application_security_percent" value="{e(p.max_application_security_percent)}" placeholder="до, %"></div></details>
<details><summary>Размер обеспечения контракта</summary><div class="range"><input class="input" name="min_contract_security_percent" value="{e(p.min_contract_security_percent)}" placeholder="от, %"><input class="input" name="max_contract_security_percent" value="{e(p.max_contract_security_percent)}" placeholder="до, %"></div></details>
<details><summary>Минимальный AI-балл</summary><input class="input" name="min_ai_score" value="{e(p.min_ai_score)}" placeholder="0–100"></details></div></section>
<div class="actions"><a class="btn" href="/">Отменить</a><button class="btn primary" type="submit">Добавить новый ключ</button></div></form></main></div></body></html>"""

def serve(settings, host="127.0.0.1", port=8080):
    db = TenderDatabase(settings.database_path)
    store = SearchProfileStore(db)
    class Handler(BaseHTTPRequestHandler):
        def send_html(self, body, status=200):
            data=body.encode("utf-8"); self.send_response(status)
            self.send_header("Content-Type","text/html; charset=utf-8"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            path=urlparse(self.path)
            user=_v(parse_qs(path.query),"user","web-local")
            profiles=store.list(user); self.send_html(render_form(profiles[0] if profiles else None, path.path=="/saved"))
        def do_POST(self):
            if urlparse(self.path).path!="/profiles": self.send_html("Not found",404); return
            try:
                length=int(self.headers.get("Content-Length","0"))
                profile=profile_from_form(parse_qs(self.rfile.read(length).decode("utf-8")))
                store.create("web-local",profile)
            except (ValueError,TypeError) as exc:
                self.send_html(render_form(profile if "profile" in locals() else SearchProfile(),False).replace("</main>",'<div class="toast">Ошибка: '+html.escape(str(exc))+"</div></main>"),400); return
            self.send_response(303); self.send_header("Location","/saved"); self.end_headers()
        def log_message(self, fmt, *args): return
    server=ThreadingHTTPServer((host,port),Handler)
    print(f"Web UI: http://{host}:{port}/"); server.serve_forever()

if __name__=="__main__":
    serve(load_settings())
