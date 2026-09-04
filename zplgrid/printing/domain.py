from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScalingPolicy(str, Enum):
    """How a document page is mapped to the loaded label."""

    HOLD = "hold"
    FIT = "fit"
    FILL = "fill"


class ContentOptimize(str, Enum):
    AUTO = "auto"
    TEXT = "text"
    GRAPHICS = "graphics"
    PHOTO = "photo"


class DitherMode(str, Enum):
    AUTO = "auto"
    NONE = "none"
    FLOYD_STEINBERG = "floyd_steinberg"


@dataclass(frozen=True)
class RasterTarget:
    width_mm: float
    height_mm: float
    dpi: int
    media_color: str = "white"
    media_color_hex: str | None = None

    @property
    def width_dots(self) -> int:
        return max(1, round(self.width_mm * self.dpi / 25.4))

    @property
    def height_dots(self) -> int:
        return max(1, round(self.height_mm * self.dpi / 25.4))


@dataclass(frozen=True)
class RasterPageSource:
    data: bytes
    mime_type: str
    width_mm: float
    height_mm: float


class MediaMismatchError(ValueError):
    def __init__(self, *, source_width_mm: float, source_height_mm: float, target: RasterTarget) -> None:
        self.source_width_mm = source_width_mm
        self.source_height_mm = source_height_mm
        self.target = target
        super().__init__(
            "Document page is "
            f"{source_width_mm:g} x {source_height_mm:g} mm but loaded media is "
            f"{target.width_mm:g} x {target.height_mm:g} mm"
        )
