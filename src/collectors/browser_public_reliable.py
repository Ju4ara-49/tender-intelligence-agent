"""Resilient browser search helpers for JS-heavy public tender portals."""
from __future__ import annotations

import logging

from src.collectors.browser_public import RtsTenderCollector, TmkCollector
from src.collectors.rosatom import RosatomCollector

logger = logging.getLogger(__name__)


class ReliableBrowserSearchMixin:
    """Search helper that tolerates delayed widgets, frames and pagination."""

    def _search_one(self, query: str):
        logger.info("%s: поиск по ключевому слову: %s", self.platform, query)
        search_control_found = False
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(locale="ru-RU")
                page = context.new_page()
                page.goto(self.BASE_URL, wait_until="domcontentloaded", timeout=self.timeout_ms)
                page.wait_for_timeout(6500)
                self._dismiss_consent(page)

                search_control_found = self._perform_search(page, query)
                if not search_control_found:
                    logger.warning(
                        "%s: SEARCH_ADAPTER_UNAVAILABLE — поле/кнопка поиска не найдены для %r; не считаем это успешным нулевым поиском",
                        self.platform,
                        query,
                    )
                    self._collect_rendered_html(page)
                    browser.close()
                    return []

                page.wait_for_timeout(4500)
                try:
                    page.wait_for_load_state("networkidle", timeout=9000)
                except Exception:
                    pass

                self._expand_results(page)
                html = self._collect_rendered_html(page)
                browser.close()
        except Exception as exc:
            logger.warning("%s: browser search failed for %r: %s", self.platform, query, exc)
            return []

        results = self._parse_results(html)
        logger.info(
            "%s: keyword=%r: search_control=%s, принято %d результатов",
            self.platform,
            query,
            search_control_found,
            len(results),
        )
        return results

    @staticmethod
    def _dismiss_consent(page) -> None:
        """Dismiss common cookie/consent overlays without bypassing access controls."""
        labels = (
            "Принять", "Принять все", "Согласен", "Согласна", "Разрешить",
            "Accept", "Accept all", "OK",
        )
        for frame in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
            for label in labels:
                try:
                    loc = frame.get_by_role("button", name=label, exact=False).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1200)
                        page.wait_for_timeout(300)
                        return
                except Exception:
                    continue
                try:
                    loc = frame.get_by_text(label, exact=True).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1200)
                        page.wait_for_timeout(300)
                        return
                except Exception:
                    continue

    def _perform_search(self, page, query: str) -> bool:
        """Find the actual search control, including delayed/embedded widgets."""
        selectors = (
            "input[type='search']",
            "input[name*='search' i]",
            "input[name*='query' i]",
            "input[name*='keyword' i]",
            "input[placeholder*='поиск' i]",
            "input[placeholder*='закуп' i]",
            "input[placeholder*='наимен' i]",
            "input[placeholder*='ключев' i]",
            "input[placeholder*='слово' i]",
            "input[aria-label*='поиск' i]",
            "input[aria-label*='закуп' i]",
            "textarea[placeholder*='поиск' i]",
            "textarea[placeholder*='ключев' i]",
            "[data-testid*='search' i] input",
            "[class*='search' i] input",
            "[contenteditable='true']",
        )
        search_labels = (
            "Найти закупку", "Поиск закупок", "Поиск", "Искать", "Найти",
            "Показать", "Показать результаты",
        )

        frames = [page.main_frame] + [frame for frame in page.frames if frame != page.main_frame]

        for frame in frames:
            for label in search_labels:
                try:
                    loc = frame.get_by_role("button", name=label, exact=False).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1500)
                        page.wait_for_timeout(700)
                        break
                except Exception:
                    continue

        for frame in frames:
            for selector in selectors:
                try:
                    loc = frame.locator(selector).first
                    if not loc.count() or not loc.is_visible():
                        continue
                    loc.fill(query)
                    try:
                        if loc.input_value() != query:
                            continue
                    except Exception:
                        pass
                    submitted = False
                    try:
                        loc.press("Enter")
                        submitted = True
                    except Exception:
                        pass
                    for label in search_labels:
                        try:
                            button = frame.get_by_role("button", name=label, exact=False).first
                            if button.count() and button.is_visible():
                                button.click(timeout=1500)
                                submitted = True
                                break
                        except Exception:
                            continue
                    if submitted:
                        return True
                except Exception:
                    continue

            try:
                textbox = frame.get_by_role("textbox").first
                if textbox.count() and textbox.is_visible():
                    textbox.fill(query)
                    textbox.press("Enter")
                    return True
            except Exception:
                pass

        return False

    @staticmethod
    def _expand_results(page) -> None:
        """Expand paginated/load-more result sets without unbounded scrolling."""
        load_more_labels = (
            "Загрузить еще", "Загрузить ещё", "Показать еще", "Показать ещё",
            "Еще", "Ещё", "Следующая", "Следующая страница", "Далее", "Next",
        )
        stable = 0
        previous = -1
        for _ in range(20):
            try:
                current = page.locator("a[href], article, tr, li").count()
            except Exception:
                current = previous
            if current == previous:
                stable += 1
            else:
                stable = 0
            if stable >= 3:
                break
            previous = current

            clicked = False
            for label in load_more_labels:
                try:
                    # Playwright Python Locator.filter() does not accept a visible= keyword.
                    # Filter first, then explicitly check visibility before clicking.
                    candidates = page.get_by_text(label, exact=False)
                    for index in range(candidates.count() - 1, -1, -1):
                        loc = candidates.nth(index)
                        try:
                            if not loc.is_visible():
                                continue
                            loc.click(timeout=1500)
                            page.wait_for_timeout(1500)
                            clicked = True
                            break
                        except Exception:
                            continue
                    if clicked:
                        break
                except Exception:
                    continue
            if not clicked:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1200)


class ReliableRtsTenderCollector(ReliableBrowserSearchMixin, RtsTenderCollector):
    """RTS-Tender with resilient search widget discovery."""


class ReliableTmkCollector(ReliableBrowserSearchMixin, TmkCollector):
    """TMK procurement portal with resilient search widget discovery."""


class ReliableRosatomCollector(ReliableBrowserSearchMixin, RosatomCollector):
    """Rosatom procurement portal with resilient search widget discovery."""
