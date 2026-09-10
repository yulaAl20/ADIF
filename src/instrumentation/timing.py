"""Per-stage runtime and memory instrumentation (M14, FR-14.4).

Uses :mod:`tracemalloc` from the standard library rather than ``psutil``. Two
reasons: it needs no extra dependency, and it measures *Python allocation*
rather than process RSS, so a reading is not polluted by whatever the operating
system happened to be doing at the time. For comparing the cost of one matching
stage against another, which is what FR-14.4 is actually for, allocation is the
more honest number.

The semantic stage is the expensive one and the most novel-sounding part of the
design. It should have to justify its cost, not merely ride along — so cost has
to be measured, not assumed.
"""

from __future__ import annotations

import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

__all__ = ["StageCost", "StageProfiler"]


@dataclass
class StageCost:
    """Accumulated cost of one pipeline stage."""

    calls: int = 0
    seconds: float = 0.0
    peak_kib: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "calls": self.calls,
            "seconds": round(self.seconds, 6),
            "mean_ms": round(1000 * self.seconds / self.calls, 4) if self.calls else 0.0,
            "peak_kib": round(self.peak_kib, 1),
        }


@dataclass
class StageProfiler:
    """Collects per-stage cost across a run.

    Tracing is off by default: :mod:`tracemalloc` slows execution noticeably,
    and a timing number taken while tracing memory is not the timing number you
    would get in normal use. Enable memory only when memory is the question.
    """

    trace_memory: bool = False
    stages: dict[str, StageCost] = field(default_factory=dict)

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        """Time one stage invocation, optionally tracking peak allocation."""
        cost = self.stages.setdefault(stage, StageCost())
        if self.trace_memory:
            tracemalloc.start()
        start = time.perf_counter()
        try:
            yield
        finally:
            cost.seconds += time.perf_counter() - start
            cost.calls += 1
            if self.trace_memory:
                _, peak = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                cost.peak_kib = max(cost.peak_kib, peak / 1024)

    def as_dict(self) -> dict[str, dict[str, float]]:
        """Report for the run record (FR-14.5)."""
        return {name: cost.as_dict() for name, cost in self.stages.items()}

    def total_seconds(self) -> float:
        return round(sum(c.seconds for c in self.stages.values()), 6)
