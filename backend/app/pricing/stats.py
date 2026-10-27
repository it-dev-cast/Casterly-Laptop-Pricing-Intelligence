"""Explainable robust statistics.

Weighted quantiles use the midpoint (Hazen-style) definition: each observation's
cumulative-weight position is ``(C_i - w_i/2) / W`` and the quantile is linearly
interpolated between positions, clamped to the min/max outside them. With equal
weights this reproduces the ordinary median (average of the middle two values
for an even count).
"""
from __future__ import annotations

from collections.abc import Sequence


def weighted_quantile(values: Sequence[float], weights: Sequence[float], q: float) -> float | None:
    pairs = sorted((float(v), float(w)) for v, w in zip(values, weights) if w > 0)
    if not pairs:
        return None
    total = sum(w for _, w in pairs)
    positions, cum = [], 0.0
    for _, w in pairs:
        cum += w
        positions.append((cum - w / 2) / total)
    if q <= positions[0]:
        return pairs[0][0]
    if q >= positions[-1]:
        return pairs[-1][0]
    for i in range(1, len(pairs)):
        if q <= positions[i]:
            p0, p1 = positions[i - 1], positions[i]
            v0, v1 = pairs[i - 1][0], pairs[i][0]
            if p1 == p0:
                return v1
            return v0 + (v1 - v0) * (q - p0) / (p1 - p0)
    return pairs[-1][0]


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float | None:
    return weighted_quantile(values, weights, 0.5)


def weighted_mad(values: Sequence[float], weights: Sequence[float], center: float) -> float | None:
    return weighted_median([abs(v - center) for v in values], weights)


def kish_effective_n(weights: Sequence[float]) -> float:
    s = sum(weights)
    s2 = sum(w * w for w in weights)
    return (s * s / s2) if s2 > 0 else 0.0


def simple_median(values: Sequence[float]) -> float | None:
    v = sorted(values)
    n = len(v)
    if n == 0:
        return None
    mid = n // 2
    return v[mid] if n % 2 else (v[mid - 1] + v[mid]) / 2
