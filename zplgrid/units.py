from __future__ import annotations

import math


_MM_PER_INCH = 25.4


def mm_to_dots(mm: float, dpi: int) -> int:
    if mm < 0:
        raise ValueError('mm must be >= 0')
    if dpi <= 0:
        raise ValueError('dpi must be > 0')
    value = (mm / _MM_PER_INCH) * dpi
    return int(math.floor(value + 0.5))


def dots_to_mm(dots: int, dpi: int) -> float:
    if dots < 0:
        raise ValueError('dots must be >= 0')
    if dpi <= 0:
        raise ValueError('dpi must be > 0')
    return (dots / dpi) * _MM_PER_INCH


def clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))
