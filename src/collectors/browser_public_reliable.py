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
                context = browser.new_context(
                    locale="ru-RU",
                    viewport={"width": 1440, "height": 1000},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/151.0.0.0 Safari/537.36"
                    ),
                )
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
                    self._log_page_state(page)
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
        if search_control_found and not results:
            logger.warning(
                "%s: RESULT_PARSER_ZERO — поиск был отправлен, но парсер не нашёл процедур для %r",
                self.platform,
                query,
            )
        return results

    @staticmethod
    def _log_page_state(page) -> None:
        """Log enough DOM state to distinguish a broken adapter from a blocked page."""
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            url = page.url
        except Exception:
            url = ""
        try:
            body = " ".join(page.locator("body").inner_text(timeout=1500).split())[:600]
        except Exception:
            body = ""
        logger.warning("browser state: url=%s title=%r body=%r", url, title, body)

    def _perform_search(self, page, query: str) -> bool:
        """Find and explicitly submit the real search form, including SPA/shadow-DOM widgets."""
        selectors = (
            "input[type='search']",
            "input[role='searchbox']",
            "input[role='textbox']",
            "input[name*='search' i]",
            "input[name*='query' i]",
            "input[name*='keyword' i]",
            "input[name*='phrase' i]",
            "input[name*='text' i]",
            "input[placeholder*='поиск' i]",
            "input[placeholder*='закуп' i]",
            "input[placeholder*='наимен' i]",
            "input[placeholder*='ключев' i]",
            "input[placeholder*='слово' i]",
            "input[placeholder*='найти' i]",
            "input[aria-label*='поиск' i]",
            "input[aria-label*='закуп' i]",
            "input[aria-label*='найти' i]",
            "textarea[placeholder*='поиск' i]",
            "[role='searchbox']",
            "[contenteditable='true']",
            "[data-testid*='search' i] input",
            "[data-test*='search' i] input",
            "[class*='search' i] input",
        )
        search_labels = (
            "Найти закупку", "Поиск закупок", "Поиск", "Искать", "Найти",
            "Найти процедуры", "Искать закупки", "Показать результаты",
            "Показать", "Применить", "Применить фильтры", "Отправить",
            "Search", "Find",
        )
        trigger_selectors = (
            "button[aria-label*='поиск' i]", "button[title*='поиск' i]",
            "button[data-testid*='search' i]", "button[data-test*='search' i]",
            "[role='button'][aria-label*='поиск' i]",
            "[role='button'][title*='поиск' i]",
            "[role='button'][data-testid*='search' i]",
            "[role='button'][data-test*='search' i]",
            "button[aria-label*='найти' i]", "button[title*='найти' i]",
            "[role='button'][aria-label*='найти' i]",
        )

        frames = [page.main_frame] + [frame for frame in page.frames if frame != page.main_frame]

        # First try explicit search/filter triggers. Some SPA portals mount the
        # real textbox only after this click.
        for frame in frames:
            for selector in trigger_selectors:
                try:
                    loc = frame.locator(selector).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1800)
                        page.wait_for_timeout(700)
                except Exception:
                    continue
            for label in search_labels:
                try:
                    loc = frame.get_by_role("button", name=label, exact=False).first
                    if loc.count() and loc.is_visible():
                        loc.click(timeout=1800)
                        page.wait_for_timeout(700)
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
                    # Prefer the portal's own submit action over Enter.
                    for label in search_labels:
                        try:
                            button = frame.get_by_role("button", name=label, exact=False).first
                            if button.count() and button.is_visible():
                                button.click(timeout=1800)
                                submitted = True
                                break
                        except Exception:
                            continue

                    if not submitted:
                        for selector_button in (
                            "button[type='submit']",
                            "input[type='submit']",
                            "form button",
                        ):
                            try:
                                button = frame.locator(selector_button).last
                                if button.count() and button.is_visible():
                                    button.click(timeout=1800)
                                    submitted = True
                                    break
                            except Exception:
                                continue

                    if not submitted:
                        try:
                            loc.press("Enter")
                            submitted = True
                        except Exception:
                            pass

                    if submitted:
                        logger.info(
                            "%s: SEARCH_SUBMITTED selector=%s frame=%s",
                            self.platform,
                            selector,
                            frame.url,
                        )
                        return True
                except Exception:
                    continue

            try:
                textbox = frame.get_by_role("textbox").first
                if textbox.count() and textbox.is_visible():
                    textbox.fill(query)
                    for label in search_labels:
                        try:
                            button = frame.get_by_role("button", name=label, exact=False).first
                            if button.count() and button.is_visible():
                                button.click(timeout=1800)
                                logger.info(
                                    "%s: SEARCH_SUBMITTED selector=role=textbox frame=%s button=%s",
                                    self.platform,
                                    frame.url,
                                    label,
                                )
                                return True
                        except Exception:
                            continue
                    textbox.press("Enter")
                    logger.info(
                        "%s: SEARCH_SUBMITTED selector=role=textbox frame=%s method=enter",
                        self.platform,
                        frame.url,
                    )
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
