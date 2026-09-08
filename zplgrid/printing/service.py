from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence
import uuid

from ..printer_services.ports import ArtifactDeliveryPort
from .domain import ContentOptimize, DitherMode, RasterPageSource, RasterTarget, ScalingPolicy
from .raster import PreparedRasterPage, encode_prepared_raster, prepare_raster_page
from ..printer_services.ports import PrintArtifact


@dataclass(frozen=True)
class DocumentDispatchResult:
    bytes_sent: int
    previews: tuple[bytes, ...]
    downstream_job_ids: tuple[str, ...]
    downstream_job_states: tuple[str, ...]
    delivery_states: tuple[str, ...] = ()


def target_for_printer(printer: Mapping[str, Any]) -> RasterTarget:
    loaded = (printer.get("media") or {}).get("loaded") or {}
    alignment = printer.get("alignment") or {}
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
    delivery_port: ArtifactDeliveryPort,
    idempotency_key_prefix: str | None = None,
) -> DocumentDispatchResult:
    if not 1 <= copies <= 999:
        raise ValueError("copies must be between 1 and 999")
    artifacts = [
        PrintArtifact(
            mime_type="application/vnd.printhub.raster-page+json",
            payload=encode_prepared_raster(page, copies=1),
            description="Prepared raster document",
        )
        for page in prepared_pages
    ]
    receipt = delivery_port.deliver_job(
        artifacts,
        printer,
        copies=copies,
        idempotency_key=idempotency_key_prefix or str(uuid.uuid4()),
        description="Prepared raster document",
        media_revision=(printer.get("media") or {}).get("revision"),
    )
    return DocumentDispatchResult(
        bytes_sent=receipt.bytes_accepted,
        previews=tuple(page.preview_png for page in prepared_pages),
        downstream_job_ids=(receipt.delivery_id,) if receipt.delivery_id else (),
        downstream_job_states=(receipt.downstream_state,) if receipt.downstream_state else (),
        delivery_states=(receipt.state.value,),
    )
