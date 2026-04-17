"""
Screen observation — post-execution visual stability detection and change tracking.

Extracted from Runner to isolate the observe→compare→classify pipeline.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from .tools import ActionResult, screenshot_hash, perceptual_diff, classify_change

log = logging.getLogger(__name__)


@dataclass
class ObservationResult:
    """Visual state after action execution."""
    screenshot: str
    hash: str
    change_score: float
    change_type: str  # "none" / "minor" / "major"


class ObservationTracker:
    """Post-execution screenshot capture and visual change detection."""

    async def wait_for_stable(
        self, kvm: object, before_ss: str,
        max_polls: int = 2, poll_interval: float = 0.4,
    ) -> str:
        """Wait for screen to stabilize after action execution.

        Returns the latest screenshot (may be same as before if no change).
        """
        ss = before_ss
        for attempt in range(max_polls):
            ss = await kvm.snapshot_b64()
            score = perceptual_diff(before_ss, ss)
            if score > 0.02:
                return ss
            if attempt < max_polls - 1:
                await asyncio.sleep(poll_interval)
        return ss

    async def capture_after(
        self, kvm: object, before_ss: str,
    ) -> ObservationResult:
        """Wait for stability, then compute visual diff."""
        after_ss = await self.wait_for_stable(kvm, before_ss)
        after_hash = screenshot_hash(after_ss)
        change_score = perceptual_diff(before_ss, after_ss)
        change_type = classify_change(change_score)
        return ObservationResult(
            screenshot=after_ss,
            hash=after_hash,
            change_score=change_score,
            change_type=change_type,
        )

    @staticmethod
    def bind_to_results(
        results: list[ActionResult], obs: ObservationResult,
    ) -> None:
        """Attach screenshot + change info to the last ActionResult."""
        if results:
            results[-1].screenshot = obs.screenshot
            results[-1].after_hash = obs.hash
            results[-1].change_score = obs.change_score
            results[-1].change_type = obs.change_type
