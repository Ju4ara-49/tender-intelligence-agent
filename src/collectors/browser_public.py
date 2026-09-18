"""Browser-based public collectors for JS-heavy tender platforms."""
from __future__ import annotations
import logging
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
from src.collectors.base import BaseCollector, CollectorUnavailableError
from src.models.tender import Tender
from src.collectors.tenderguru_fallback import search as tenderguru_search
logger = logging.getLogger(__name__)

class _BrowserTenderCollector(BaseCollector):
    BASE_URL=""
    SEARCH_HINTS: tuple[str,...]=()
    LINK_HINTS: tuple[str,...]=( "procedure","tender","zakup","purchase")
    def __init__(self, config: dict|None=None)->None:
        self.config=config or {}; self.timeout_ms=int(self.config.get("timeout_seconds",30))*1000; self.max_results=int(self.config.get("max_results",100)); self._urls={}
    def is_enabled(self, config: dict)->bool: return bool(config.get("collectors",{}).get(self.platform,{}).get("enabled",True))
    def search(self, keywords:list[str], since:datetime|None=None)->list[Tender]:
        terms=[str(x).strip() for x in keywords if str(x).strip()]
        if not terms:return []
        merged={}
        for term in terms:
            for tender in self._search_one(term):
                if since is not None and tender.published_at is not None:
                    published=tender.published_at if tender.published_at.tzinfo else tender.published_at.astimezone()
                    if published<since:continue
                merged[tender.unique_key]=tender
                if len(merged)>=self.max_results:break
            if len(merged)>=self.max_results:break
        return list(merged.values())[:self.max_results]
    @staticmethod
    def _wait_for_initial_dom(page)->None:
        try:page.wait_for_load_state("domcontentloaded",timeout=10000)
        except Exception:pass
        try:page.locator("body").wait_for(state="attached",timeout=5000)
        except Exception:pass
    def _goto(self,page,url:str)->None:
        page.goto(url,wait_until="commit",timeout=self.timeout_ms); self._wait_for_initial_dom(page)
    def _search_one(self,query:str)->list[Tender]:
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True); page=browser.new_page(locale="ru-RU")
                try:
                    self._goto(page,self.BASE_URL); page.wait_for_timeout(1800)
                    if not self._perform_search(page,query):raise CollectorUnavailableError(f"{self.platform}: search control unavailable for {query!r}")
                    page.wait_for_timeout(3000)
                    try:page.wait_for_load_state("networkidle",timeout=7000)
                    except Exception:pass
                    html=self._collect_rendered_html(page)
                finally:browser.close()
        except PlaywrightTimeoutError as exc:
            if self.platform=="rts_tender":return self._tenderguru_fallback(query,exc)
            raise CollectorUnavailableError(f"{self.platform}: browser timeout for {query!r}: {exc}") from exc
        except CollectorUnavailableError:raise
        except Exception as exc:
            if self.platform=="rts_tender":return self._tenderguru_fallback(query,exc)
            raise CollectorUnavailableError(f"{self.platform}: browser search unavailable for {query!r}: {type(exc).__name__}: {exc}") from exc
        soup_text=" ".join(BeautifulSoup(html,"html.parser").stripped_strings).lower()
        if any(x in soup_text for x in ("web application firewall","временно заблокирован","пожалуйста подождите","для работы с сайтом необходимы включенные javascript и cookies")):
            raise CollectorUnavailableError(f"{self.platform}: portal returned access/challenge page")
        parsed=self._parse_results(html); return [t for t in parsed if self._tender_matches_query(t,query)]
    def _tenderguru_fallback(self,query:str,reason:Exception)->list[Tender]:
        try:results=tenderguru_search(platform=self.platform,keyword=query,timeout=min(max(self.timeout_ms//1000,10),20),max_results=self.max_results)
        except Exception as exc:raise CollectorUnavailableError(f"{self.platform}: fallback failed: {exc}") from exc
        if not results:raise CollectorUnavailableError(f"{self.platform}: fallback returned no results for {query!r}")
        return [t for t in results if self._tender_matches_query(t,query)]
    @classmethod
    def _tender_matches_query(cls,tender:Tender,query:str)->bool:
        q=cls._normalize_search_text(query)
        if not q:return False
        text=cls._normalize_search_text(" ".join((tender.title or "",tender.description or "",str((tender.raw_data or {}).get("subject") or ""))))
        if q in text:return True
        variants={
            "станок":("станок","станка","станки","станков","станкам","станками","станке","станком"),
            "подшипник":("подшипник","подшипника","подшипники","подшипников","подшипнику","подшипникам","подшипником","подшипниками","подшипнике","подшипниках"),
            "лебедка":("лебедка","лебедки","лебедку","лебедкой","лебедок","лебедкам","лебедками","лебедкою"),
            "редуктор":("редуктор","редуктора","редукторы","редукторов","редукторам","редукторами","редукторе","редуктором")}
        # Resolve q to its canonical group regardless of declined form: a
        # plain variants.get(q, ()) only matched when q was already the
        # nominative singular key, so any other form of the same word
        # (plural, genitive, etc.) silently matched nothing.
        forms=variants.get(q)
        if forms is None:
            for group in variants.values():
                if q in group:forms=group;break
        return any(re.search(rf"(?<![а-яёa-z0-9]){re.escape(v)}(?![а-яёa-z0-9])",text) for v in (forms or ()))
    @staticmethod
    def _normalize_search_text(value:str)->str:return re.sub(r"[^0-9a-zа-яё]+"," ",str(value or "").casefold()).strip()
    def get_details(self,external_id:str)->Tender|None:
        url=self._urls.get(str(external_id))
        if not url:return None
        try:
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True); page=browser.new_page(locale="ru-RU")
                try:
                    self._goto(page,url); page.wait_for_timeout(2500); self._open_information_sections(page); page.wait_for_timeout(1200); html=self._collect_rendered_html(page)
                finally:browser.close()
            soup_text=" ".join(BeautifulSoup(html,"html.parser").stripped_strings).lower()
            if any(x in soup_text for x in ("web application firewall","временно заблокирован","пожалуйста подождите")):return None
            return self._parse_detail(html,str(external_id),url)
        except Exception as exc:logger.warning("%s: detail failed %s: %s",self.platform,external_id,exc); return None
    @staticmethod
    def _collect_rendered_html(page)->str:
        chunks=[]
        try:chunks.append(page.content())
        except Exception:pass
        for frame in page.frames:
            if frame==page.main_frame:continue
            try:
                value=frame.content()
                if value:chunks.append(value)
            except Exception:continue
        return "\n".join(chunks)
    @staticmethod
    def _open_information_sections(page)->None:
        for label in ("Общая информация","Сведения о закупке","Информация о закупке","Основная информация","Сведения","Условия закупки"):
            try:
                loc=page.get_by_text(label,exact=False)
                for idx in range(min(loc.count(),3)):
                    item=loc.nth(idx)
                    if item.is_visible():item.click(timeout=1000); page.wait_for_timeout(250)
            except Exception:continue
    def _perform_search(self,page,query:str)->bool:
        selectors=["input[type='search']","input[name*='search' i]","input[name*='query' i]","input[placeholder*='поиск' i]","input[placeholder*='закуп' i]","input[placeholder*='наимен' i]","input[placeholder*='ключев' i]","input[placeholder*='предмет' i]","input[aria-label*='поиск' i]","input[aria-label*='закуп' i]","input[aria-label*='найти' i]"]
        for selector in selectors:
            try:
                loc=page.locator(selector).first
                if loc.count() and loc.is_visible():loc.fill(query); loc.press("Enter"); return True
            except Exception:continue
        for label in self.SEARCH_HINTS:
            try:
                button=page.get_by_text(label,exact=False).first
                if button.count() and button.is_visible():button.click(); page.wait_for_timeout(700); break
            except Exception:continue
        for selector in selectors:
            try:
                loc=page.locator(selector).first
                if loc.count() and loc.is_visible():loc.fill(query); loc.press("Enter"); return True
            except Exception:continue
        return False
    def _parse_results(self,html:str)->list[Tender]:
        soup=BeautifulSoup(html,"html.parser"); results=[]; seen=set(); base_host=urlparse(self.BASE_URL).netloc.lower(); onclick_re=re.compile(r"(?:location(?:\.href)?\s*=|window\.location(?:\.href)?\s*=|window\.open\s*\()\s*['\"]([^'\"]+)['\"]",re.I)
        for node in soup.find_all(True):
            raw=None
            for attr in ("href","data-href","data-url","data-link","routerlink","data-routerlink"):
                if node.get(attr):raw=str(node.get(attr)).strip();break
            if not raw:
                m=onclick_re.search(str(node.get("onclick","")))
                if m:raw=m.group(1).strip()
            if not raw or raw.lower().startswith(("javascript:","#")):continue
            href=urljoin(self.BASE_URL,raw); parsed=urlparse(href)
            if parsed.netloc and parsed.netloc.lower()!=base_host:continue
            title=" ".join(node.stripped_strings)
            if len(title)<5 and node.parent is not None:title=" ".join(node.parent.stripped_strings)
            if len(title)<5:continue
            if not any(h in href.lower() for h in self.LINK_HINTS) and not re.search(r"\d{6,}",href+" "+title):continue
            external_id=self._extract_id(href,title)
            if not external_id or external_id in seen:continue
            seen.add(external_id); self._urls[external_id]=href; results.append(Tender(platform=self.platform,external_id=external_id,title=title[:1000],url=href,description=title,raw_data={"source":self.BASE_URL}))
        return results
    def _parse_detail(self,html:str,external_id:str,url:str)->Tender:
        soup=BeautifulSoup(html,"html.parser"); title_node=soup.find("h1") or soup.find("title"); title=" ".join(title_node.stripped_strings) if title_node else f"Процедура {external_id}"; text=" ".join(soup.stripped_strings); price=self._extract_price(text); deadline=self._extract_date(text); published=self._extract_datetime(text,("Дата публикации","Дата размещения","Опубликовано","Размещено")); start=self._extract_datetime(text,("Дата начала","Начало приема","Начало подачи")); end=deadline or self._extract_datetime(text,("Дата окончания","Окончание приема","Окончание подачи")); customer=self._extract_labeled_value(text,("Заказчик","Организатор","Организация-заказчик")); region=self._extract_labeled_value(text,("Регион поставки","Место поставки","Место выполнения","Регион")); law=self._extract_labeled_value(text,("Закон","Вид закона","Федеральный закон","Тип закупки")); advance=self._extract_percent(text,("Аванс","Предоплата","Размер аванса")); post=self._extract_days(text,("Отсрочка платежа","Срок оплаты","Условия оплаты","Постоплата")); app=self._extract_percent(text,("Обеспечение заявки","Обеспечение предложения")); contract=self._extract_percent(text,("Обеспечение исполнения","Обеспечение контракта","Обеспечение договора")); documents=self._extract_documents(soup,url); raw={"source":url,"published_at":published.isoformat() if published else None,"start_date":start.isoformat() if start else None,"end_date":end.isoformat() if end else None}
        if documents: raw["documents"]=documents
        if advance is not None:raw["advance_payment"]={"percent":advance}
        if post is not None:raw["postpayment"]={"days":post}
        if app is not None:raw["application_security"]={"percent":app}
        if contract is not None:raw["contract_security"]={"percent":contract}
        return Tender(platform=self.platform,external_id=external_id,title=title[:1000],url=url,description=text[:10000],price=price,deadline=end,published_at=published,start_date=start,end_date=end,region=region,customer=customer,law_type=law,advance_required=advance is not None and advance>0,advance_percent=advance,postpayment_days=post,application_security_percent=app,contract_security_percent=contract,documents=documents,raw_data=raw)

    @staticmethod
    def _extract_documents(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        """Extract explicit downloadable tender attachments from rendered detail HTML."""
        documents: list[dict[str, str]] = []
        seen: set[str] = set()
        extensions = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".rar")
        hints = ("документ", "вложен", "приложен", "скачать", "download", "attachment", "file")
        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:")):
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            label = " ".join(anchor.stripped_strings).strip()
            haystack = f"{absolute} {label}".casefold()
            if not (any(h in haystack for h in hints) or any(ext in parsed.path.casefold() for ext in extensions)):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            filename = Path(parsed.path).name or label or "document"
            item = {"url": absolute, "filename": filename[:500]}
            lowered = filename.casefold()
            for ext, mime in (
                (".pdf", "application/pdf"), (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                (".csv", "text/csv"), (".zip", "application/zip"),
            ):
                if lowered.endswith(ext):
                    item["content_type"] = mime
                    break
            documents.append(item)
        return documents
    @staticmethod
    def _extract_labeled_value(text:str,labels:tuple[str,...])->str:
        lp="|".join(re.escape(x) for x in labels); m=re.search(rf"(?:{lp})\s*[:\-]?\s*(.+?)(?=\s+(?:Заказчик|Организатор|Регион|Место|Дата|Срок|Цена|НМЦ|Обеспечение|Аванс|Оплата)\b|$)",text,re.I); return m.group(1).strip(" ;,\t")[:1000] if m else ""
    @staticmethod
    def _extract_percent(text:str,labels:tuple[str,...])->float|None:
        lp="|".join(re.escape(x) for x in labels); m=re.search(rf"(?:{lp})[^%\d]{{0,60}}(\d+(?:[.,]\d+)?)\s*%",text,re.I)
        try:return float(m.group(1).replace(",",".")) if m else None
        except ValueError:return None
    @staticmethod
    def _extract_days(text:str,labels:tuple[str,...])->int|None:
        lp="|".join(re.escape(x) for x in labels); m=re.search(rf"(?:{lp})[^\d]{{0,60}}(\d{{1,4}})\s*(?:дн\w*|сут\w*)",text,re.I); return int(m.group(1)) if m else None
    @staticmethod
    def _extract_datetime(text:str,labels:tuple[str,...])->datetime|None:
        lp="|".join(re.escape(x) for x in labels); m=re.search(rf"(?:{lp})[^0-9]{{0,60}}(\d{{1,2}})[./](\d{{1,2}})[./](20\d{{2}})(?:[^0-9]{{0,20}}(\d{{1,2}}):([0-9]{{2}}))?",text,re.I)
        if not m:return None
        try:return datetime(int(m.group(3)),int(m.group(2)),int(m.group(1)),int(m.group(4) or 0),int(m.group(5) or 0))
        except ValueError:return None
    @staticmethod
    def _extract_id(href:str,title:str)->str|None:
        for source in (href,title):
            for pattern in (r"(?:procedure|tender|purchase)[^0-9]{0,30}(\d{5,})",r"(?:/|#)l(\d{6,})(?:[-/]|$)",r"(?:/|#)(\d{6,})(?:/|$)",r"\b(\d{7,})\b"):
                m=re.search(pattern,source,re.I)
                if m:return m.group(1)
        return None
    @staticmethod
    def _extract_price(text:str)->float|None:
        for m in re.finditer(r"(?:цена|стоимость|НМЦ|начальн\w* цена)[^0-9]{0,40}([0-9][0-9\s]{2,}(?:[.,][0-9]{1,2})?)",text,re.I):
            try:return float(m.group(1).replace(" ","").replace(",","."))
            except ValueError:continue
        return None
    @staticmethod
    def _extract_date(text:str)->datetime|None:
        m=re.search(r"(?:до|окончани\w*|срок[^0-9]{0,10})[^0-9]{0,30}(\d{1,2})[./](\d{1,2})[./](20\d{2})",text,re.I)
        if not m:return None
        try:return datetime(int(m.group(3)),int(m.group(2)),int(m.group(1)))
        except ValueError:return None

class RtsTenderCollector(_BrowserTenderCollector):
    platform="rts_tender"; BASE_URL="https://223.rts-tender.ru/"; SEARCH_HINTS=("Поиск","Поиск закупок","Закупки"); LINK_HINTS=("/poisk/","/procedure","/tender","zakup")
class TmkCollector(_BrowserTenderCollector):
    platform="tmk"; BASE_URL="https://stock.tmk-group.com/auction/"; SEARCH_HINTS=("Применить","Поиск","Найти"); LINK_HINTS=("/auction/","stock.tmk-group.com")
