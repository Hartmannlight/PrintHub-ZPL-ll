from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from ..fleet.ports import ArtifactDeliveryPort
from ..printer_media import resolve_dynamic_printer_media
from .adapters import backend_for, raster_driver_for
from .domain import ContentOptimize, DitherMode, RasterPageSource, RasterTarget, ScalingPolicy
from .raster import PreparedRasterPage, prepare_raster_page


@dataclass(frozen=True)
class DocumentDispatchResult:
    bytes_sent: int
    previews: tuple[bytes, ...]
    downstream_job_ids: tuple[str, ...]
    downstream_job_states: tuple[str, ...]
    delivery_states: tuple[str, ...] = ()


def target_for_printer(printer: Mapping[str, Any]) -> RasterTarget:
    resolved = resolve_dynamic_printer_media(dict(printer))
    loaded = (resolved.get("media") or {}).get("loaded") or {}
    alignment = resolved.get("alignment") or {}
    if not loaded or not alignment.get("dpi"):
        raise ValueError("Loaded media and printer resolution are required for raster printing")
    return RasterTarget(
        width_mm=float(loaded["width_mm"]),
        height_mm=float(loaded["height_mm"]),
        dpi=int(alignment["dpi"]),
        media_color=str(loaded.get("color") or "white"),
        media_color_hex=str(loaded["color_hex"]) if loaded.get("color_hex") else None,
    )


def prepare_document(
    printer: Mapping[str, Any],
    pages: Sequence[RasterPageSource],
    *,
    scaling: ScalingPolicy,
    content_optimize: ContentOptimize,
    dither: DitherMode,
    mismatch_tolerance_mm: float,
) -> tuple[PreparedRasterPage, ...]:
    if not pages:
        raise ValueError("A raster document must contain at least one page")
    target = target_for_printer(printer)
    return tuple(
        prepare_raster_page(
            page,
            target=target,
            scaling=scaling,
            content_optimize=content_optimize,
            dither=dither,
            mismatch_tolerance_mm=mismatch_tolerance_mm,
        )
        for page in pages
    )


def dispatch_document(
    printer: Mapping[str, Any],
    prepared_pages: Sequence[PreparedRasterPage],
    *,
    copies: int,
    delivery_port: ArtifactDeliveryPort | None = None,
    idempotency_key_prefix: str | None = None,
) -> DocumentDispatchResult:
    if not 1 <= copies <= 999:
        raise ValueError("copies must be between 1 and 999")
    configured_printer = dict(printer)
    configured_printer["defaults"] = {**dict(printer.get("defaults") or {}), "copies": copies}
    driver = raster_driver_for(configured_printer)
    backend = delivery_port or backend_for(configured_printer)
    bytes_sent = 0
    job_ids: list[str] = []
    job_states: list[str] = []
    delivery_states: list[str] = []
    for page_number, page in enumerate(prepared_pages, start=1):
        artifact = driver.prepare(page, configured_printer)
        if idempotency_key_prefix:
            artifact = replace(
                artifact,
                idempotency_key=f"{idempotency_key_prefix}/page-{page_number}",
            )
        receipt = backend.deliver(artifact, configured_printer)
        bytes_sent += receipt.bytes_accepted
        delivery_states.append(receipt.state.value)
        if receipt.delivery_id:
            job_ids.append(receipt.delivery_id)
        if receipt.downstream_state:
            job_states.append(receipt.downstream_state)
    return DocumentDispatchResult(
        bytes_sent=bytes_sent,
        previews=tuple(page.preview_png for page in prepared_pages),
        downstream_job_ids=tuple(job_ids),
        downstream_job_states=tuple(job_states),
        delivery_states=tuple(delivery_states),
    )
