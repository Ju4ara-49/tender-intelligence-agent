"""More resilient browser search mixin for JS-heavy public tender portals."""
from __future__ import annotations

import logging

from src.collectors.browser_public import RtsTenderCollector, TmkCollector
from src.collectors.rosatom import RosatomCollector

logger = logging.getLogger(__name__)


class ReliableBrowserSearchMixin:
    """Search helper that tolerates delayed widgets, frames and pagination."""

    def _search_one(self, query: str):
        logger.info("%s: поиск по ключевому слову: %s", self.platform, query)
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(locale="ru-RU")
                page = context.new_page()
                page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(5000)

                if not self._perform_search(page, query):
                    logger.warning("%s: не удалось обнаружить рабочий виджет поиска для %r", self.platform, query)
                    browser.close()
                    return []

                page.wait_for_timeout(3500)
                try:
                    page.wait_for_load_state("networkidle", timeout=7000)
                except Exception:
                    pass

                self._expand_results(page)
                html = self._collect_rendered_html(page)
                browser.close()
        except Exception as exc:
            logger.warning("%s: browser search failed for %r: %s", self.platform, query, exc)
            return []

        results = self._parse_results(html)
        logger.info("%s: keyword=%r: принято %d результатов", self.platform, query, len(results))
        return results

    def _perform_search(self, page, query: str) -> bool:
        selectors = (
            "input[type='search']",
            "input:not([type='hidden']):not([type='submit']):not([type='button'])",
            "textarea",
            "[contenteditable='true']",
        )
        search_labels = ("Найти", "Искать", "Поиск", "Найти закупку", "Поиск закупок")

        frames = [page.main_frame] + [frame for frame in page.frames if frame != page.main_frame]
        for frame in frames:
            for selector in selectors:
                try:
                    loc = frame.locator(selector).filter(visible=True).first
                    if not loc.count():
                        continue
                    loc.fill(query)
                    try:
                        loc.press("Enter")
                    except Exception:
                        pass
                    for label in search_labels:
                        try:
                            button = frame.get_by_text(label, exact=False).filter(visible=True).first
                            if button.count():
                                button.click(timeout=1200)
                                break
                        except Exception:
                            continue
                    return True
                except Exception:
                    continue

            try:
                textbox = frame.get_by_role("textbox").filter(visible=True).first
                if textbox.count():
                    textbox.fill(query)
                    textbox.press("Enter")
                    return True
            except Exception:
                pass

            for label in search_labels:
                try:
                    button = frame.get_by_text(label, exact=False).filter(visible=True).first
                    if button.count():
                        button.click(timeout=1200)
                        page.wait_for_timeout(500)
                        for selector in selectors:
                            try:
                                loc = frame.locator(selector).filter(visible=True).first
                                if loc.count():
                                    loc.fill(query)
                                    loc.press("Enter")
                                    return True
                            except Exception:
                                continue
                except Exception:
                    continue

        return False

    @staticmethod
    def _expand_results(page) -> None:
        load_more_labels = (
            "Загрузить еще", "Показать еще", "Показать ещё", "Еще", "Ещё",
            "Следующая", "Следующая страница", "Далее", "Next",
        )
        stable = 0
        previous = -1
        for _ in range(10):
            try:
                current = page.locator("a[href], article, tr, li").count()
            except Exception:
                current = previous
            if current == previous:
                stable += 1
            else:
                stable = 0
            if stable >= 2:
                break
            previous = current

            clicked = False
            for label in load_more_labels:
                try:
                    loc = page.get_by_text(label, exact=False).filter(visible=True).last
                    if loc.count():
                        loc.click(timeout=1000)
                        page.wait_for_timeout(1200)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1000)


class ReliableRtsTenderCollector(ReliableBrowserSearchMixin, RtsTenderCollector):
    """RTS-Tender with resilient search widget discovery."""


class ReliableTmkCollector(ReliableBrowserSearchMixin, TmkCollector):
    """TMK procurement portal with resilient search widget discovery."""


class ReliableRosatomCollector(ReliableBrowserSearchMixin, RosatomCollector):
    """Rosatom procurement portal with resilient search widget discovery."""
