from __future__ import annotations

from dataclasses import dataclass
import io
import math
import os

from PIL import Image, ImageColor, ImageOps

from .domain import (
    ContentOptimize,
    DitherMode,
    MediaMismatchError,
    RasterPageSource,
    RasterTarget,
    ScalingPolicy,
)


SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/x-portable-graymap"}


@dataclass(frozen=True)
class PreparedRasterPage:
    monochrome: Image.Image
    preview_png: bytes
    source_width_mm: float
    source_height_mm: float
    target: RasterTarget


def prepare_raster_page(
    source: RasterPageSource,
    *,
    target: RasterTarget,
    scaling: ScalingPolicy,
    content_optimize: ContentOptimize = ContentOptimize.AUTO,
    dither: DitherMode = DitherMode.AUTO,
    mismatch_tolerance_mm: float = 0.5,
) -> PreparedRasterPage:
    if source.mime_type not in SUPPORTED_IMAGE_TYPES:
        raise ValueError(f"Unsupported raster MIME type: {source.mime_type}")
    if source.width_mm <= 0 or source.height_mm <= 0:
        raise ValueError("Raster page dimensions must be positive")
    if mismatch_tolerance_mm < 0 or not math.isfinite(mismatch_tolerance_mm):
        raise ValueError("mismatch_tolerance_mm must be a finite non-negative number")

    mismatch = (
        abs(source.width_mm - target.width_mm) > mismatch_tolerance_mm
        or abs(source.height_mm - target.height_mm) > mismatch_tolerance_mm
    )
    if mismatch and scaling is ScalingPolicy.HOLD:
        raise MediaMismatchError(
            source_width_mm=source.width_mm,
            source_height_mm=source.height_mm,
            target=target,
        )

    try:
        with Image.open(io.BytesIO(source.data)) as opened:
            maximum_pixels = max(1, int(os.getenv("ZPLGRID_RASTER_MAX_SOURCE_PIXELS", "100000000")))
            if opened.width <= 0 or opened.height <= 0 or opened.width * opened.height > maximum_pixels:
                raise ValueError("Image dimensions exceed the configured raster limit")
            opened.load()
            image = _flatten_transparency(opened)
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid or unsupported image data") from exc

    fitted = _fit_to_target(
        image,
        width=target.width_dots,
        height=target.height_dots,
        scaling=ScalingPolicy.FIT if scaling is ScalingPolicy.HOLD else scaling,
    )
    grayscale = ImageOps.grayscale(fitted)
    effective_dither = _effective_dither(dither, content_optimize)
    if effective_dither is DitherMode.FLOYD_STEINBERG:
        mono = grayscale.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
    else:
        mono = grayscale.point(lambda value: 255 if value >= 128 else 0, mode="1")

    preview = _preview_png(mono, target)
    return PreparedRasterPage(
        monochrome=mono,
        preview_png=preview,
        source_width_mm=source.width_mm,
        source_height_mm=source.height_mm,
        target=target,
    )


def encode_zpl_graphic(page: PreparedRasterPage) -> str:
    image = page.monochrome
    width, height = image.size
    bytes_per_row = (width + 7) // 8
    encoded = bytearray(bytes_per_row * height)
    pixels = image.load()
    for y in range(height):
        row_offset = y * bytes_per_row
        for x in range(width):
            if pixels[x, y] == 0:
                encoded[row_offset + (x // 8)] |= 0x80 >> (x % 8)
    payload = encoded.hex().upper()
    total = len(encoded)
    return (
        "^XA\n"
        f"^PW{width}\n"
        f"^LL{height}\n"
        "^FO0,0\n"
        f"^GFA,{total},{total},{bytes_per_row},{payload}\n"
        "^FS\n"
        "^XZ\n"
    )


def _flatten_transparency(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    return white.convert("RGB")


def _fit_to_target(image: Image.Image, *, width: int, height: int, scaling: ScalingPolicy) -> Image.Image:
    resampling = Image.Resampling.LANCZOS
    if scaling is ScalingPolicy.FILL:
        return ImageOps.fit(image, (width, height), method=resampling, centering=(0.5, 0.5))
    contained = ImageOps.contain(image, (width, height), method=resampling)
    canvas = Image.new("RGB", (width, height), "white")
    canvas.paste(contained, ((width - contained.width) // 2, (height - contained.height) // 2))
    return canvas


def _effective_dither(dither: DitherMode, content: ContentOptimize) -> DitherMode:
    if dither is not DitherMode.AUTO:
        return dither
    return DitherMode.FLOYD_STEINBERG if content is ContentOptimize.PHOTO else DitherMode.NONE


def _preview_png(image: Image.Image, target: RasterTarget) -> bytes:
    try:
        background = ImageColor.getrgb(target.media_color_hex or target.media_color or "white")
    except ValueError:
        background = (255, 255, 255)
    preview = Image.new("RGB", image.size, background)
    black = Image.new("RGB", image.size, "black")
    ink_mask = ImageOps.invert(image.convert("L"))
    preview.paste(black, mask=ink_mask)
    output = io.BytesIO()
    preview.save(output, format="PNG", optimize=True)
    return output.getvalue()
