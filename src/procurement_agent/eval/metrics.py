from __future__ import annotations

from statistics import mean
from typing import Iterable


def success_rate(results: Iterable[bool]) -> float:
    items = list(results)
    if not items:
        return 0.0
    return sum(1 for item in items if item) / len(items)


def intervention_rate(interventions: Iterable[bool]) -> float:
    return success_rate(interventions)


def average_duration(durations_ms: Iterable[float]) -> float:
    items = [value for value in durations_ms]
    return round(mean(items), 2) if items else 0.0


def token_peak(peaks: Iterable[int]) -> int:
    items = [int(value) for value in peaks]
    return max(items) if items else 0


def token_mean(peaks: Iterable[int]) -> float:
    items = [int(value) for value in peaks]
    return round(mean(items), 2) if items else 0.0

