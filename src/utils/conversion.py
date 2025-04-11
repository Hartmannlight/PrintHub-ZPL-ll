"""
Utility functions for unit conversions.
"""
from src.config import DPI


def mm_to_inches(mm: float) -> float:
    """Convert millimeters to inches."""
    return mm / 25.4


def inches_to_mm(inches: float) -> float:
    """Convert inches to millimeters."""
    return inches * 25.4


def mm_to_pixels(mm: float, dpi: int = DPI) -> int:
    """Convert millimeters to pixels."""
    return int(mm / 25.4 * dpi)


def pixels_to_mm(pixels: int, dpi: int = DPI) -> float:
    """Convert pixels to millimeters."""
    return pixels * 25.4 / dpi


def inches_to_pixels(inches: float, dpi: int = DPI) -> int:
    """Convert inches to pixels."""
    return int(inches * dpi)


def pixels_to_inches(pixels: int, dpi: int = DPI) -> float:
    """Convert pixels to inches."""
    return pixels / dpi
