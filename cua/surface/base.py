"""The surface seam (brief §3.7).

Everything above this interface — the artifact, replay engine, discovery loop, result contract —
speaks *roles, names, checkpoints*, never CSS or pixels. That is what lets the same recorded flow
extend from a web app to a legacy web app to a desktop app: only the Surface implementation
changes. If any component above this seam referenced a Playwright object or a CSS selector
directly, the seam would leak and §3.7 would be lost.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..schema import Locator


class LocatorMiss(Exception):
    """Raised when a Locator resolves to zero elements after exhausting its fallback chain.

    A miss is surfaced loudly (with the rungs tried) rather than silently no-op'd — a click that
    quietly hits nothing is the kind of silent failure that produces a "successful" run with the
    wrong result.
    """

    def __init__(self, locator: Locator, tried: list[str]):
        self.locator = locator
        self.tried = tried
        super().__init__(f"locator resolved to 0 elements; tried rungs: {tried}")


@dataclass
class Observation:
    """What the agent perceives on each loop turn. Data contract, no Playwright types."""

    aria_snapshot: str
    url: str
    screenshot_path: str | None = None


@dataclass
class ActResult:
    ok: bool = True
    rung: str | None = None                 # which locator rung resolved the target (evidence/drift)
    blocked: str | None = None              # set by the policy guard when an action is refused
    extra: dict = field(default_factory=dict)


class Surface:
    """Perceive/act contract. Implementations: WebSurface (built), LegacyWebSurface/DesktopSurface
    (design-only per §3.7 — they slot in here without touching anything above)."""

    def goto(self, url: str) -> None: ...
    def perceive(self, screenshot: bool = False) -> Observation: ...
    def act(self, op: str, target: Locator, value: str | None = None,
            option_label: str | None = None) -> ActResult: ...
    def find_text(self, text: str) -> int: ...
    def wait_for_text(self, text: str, timeout_ms: int) -> bool: ...
    def read_row_value(self, row_label: str) -> str: ...
    def alert_text(self) -> str | None: ...
    def close(self) -> None: ...
