"""WebSurface — the browser implementation of the Surface seam, via Playwright.

Perception is the accessibility tree (`aria_snapshot`), not the DOM or pixels: on legacy
table-based bank pages with no test-ids, the a11y role+name is the most stable identity we can
get, and it is exactly what a screen-reader-driven human operator would key on. Screenshots are
optional evidence, not the perception channel — see REPORT §3 for the cost/robustness argument
against a screenshot-stability loop.
"""
from __future__ import annotations

from playwright.sync_api import Locator as PWLocator
from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from ..schema import Locator
from .base import ActResult, LocatorMiss, Observation, Surface


class WebSurface(Surface):
    def __init__(self, headless: bool = True):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self.page: Page = self._browser.new_page()

    # ---- perception ----
    def goto(self, url: str) -> None:
        self.page.goto(url)

    def perceive(self, screenshot: bool = False) -> Observation:
        snap = self.page.locator("body").aria_snapshot()
        shot = None
        return Observation(aria_snapshot=snap, url=self.page.url, screenshot_path=shot)

    # ---- the fallback locator chain (robustness rungs, top to bottom) ----
    def resolve(self, loc: Locator) -> tuple[PWLocator, str]:
        """Return (element, rung_label). Raise LocatorMiss with the rungs tried if none resolve.

        The rung that actually hit is returned so replay/evidence can record locator drift —
        a flow that starts resolving on rung 3 instead of rung 1 is an early warning the surface
        changed, even while it still succeeds.
        """
        tried: list[str] = []
        if loc.role and loc.name:
            el = self.page.get_by_role(loc.role, name=loc.name)
            if el.count():
                return el.first, "1:role+name"
            tried.append("1:role+name")
        if loc.text:
            el = self.page.get_by_text(loc.text)
            if el.count():
                return el.first, "2:text"
            tried.append("2:text")
        if loc.css:
            el = self.page.locator(loc.css)
            if el.count():
                return el.first, "3:css/structural"
            tried.append("3:css/structural")
        if loc.coords:
            # vision fallback: only reached when no DOM identity resolves. Recorded, never silent.
            return self.page.locator("body"), "4:coords"
        raise LocatorMiss(loc, tried)

    def act(self, op: str, target: Locator, value: str | None = None,
            option_label: str | None = None) -> ActResult:
        if op == "navigate":
            self.page.goto(value)
            return ActResult(ok=True, rung="0:navigate")
        el, rung = self.resolve(target)
        if op == "fill":
            el.fill(value)
        elif op == "click":
            if target.coords:                       # rung-4 path: click the recorded point
                el.click(position={"x": target.coords[0], "y": target.coords[1]})
            else:
                el.click()
        elif op == "select":
            el.select_option(label=option_label) if option_label else el.select_option(value)
        else:
            raise ValueError(f"unknown op {op!r}")
        return ActResult(ok=True, rung=rung)

    # ---- checkpoint / extraction / outcomes ----
    def find_text(self, text: str) -> int:
        return self.page.get_by_text(text).count()

    def wait_for_text(self, text: str, timeout_ms: int) -> bool:
        try:
            self.page.get_by_text(text).wait_for(timeout=timeout_ms)
            return True
        except PWTimeout:
            return False

    def read_row_value(self, row_label: str) -> str:
        row = self.page.locator("tr", has=self.page.get_by_text(row_label, exact=True))
        return row.locator("td").last.inner_text()

    def alert_text(self) -> str | None:
        a = self.page.get_by_role("alert")
        return a.first.inner_text() if a.count() else None

    def loading_text(self) -> str:
        return (self.page.get_by_text("Loading...").first.inner_text()
                if self.page.get_by_text("Loading...").count() else "(none)")

    def click_button(self, name: str) -> None:
        """Escalation/recovery helper: click a named button directly (operator or recovery action)."""
        self.page.get_by_role("button", name=name).click()

    def close(self) -> None:
        self._browser.close()
        self._pw.stop()
