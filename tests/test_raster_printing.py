from __future__ import annotations

import io

from PIL import Image
import pytest

from zplgrid import api
from zplgrid.printing.adapters import ZplRasterDriver, backend_for, raster_driver_for
from zplgrid.printing.domain import (
    ContentOptimize,
    DitherMode,
    MediaMismatchError,
    RasterPageSource,
    RasterTarget,
    ScalingPolicy,
)
from zplgrid.printing.raster import encode_zpl_graphic, prepare_raster_page
from zplgrid.printing.service import DocumentDispatchResult


def _png(*, color: str = "black", size: tuple[int, int] = (10, 10)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def test_mismatched_page_is_held_before_image_processing() -> None:
    with pytest.raises(MediaMismatchError, match="210 x 297 mm"):
        prepare_raster_page(
            RasterPageSource(_png(), "image/png", 210, 297),
            target=RasterTarget(50, 50, 203),
            scaling=ScalingPolicy.HOLD,
        )


def test_fit_preserves_page_and_label_dimensions() -> None:
    prepared = prepare_raster_page(
        RasterPageSource(_png(size=(20, 10)), "image/png", 100, 50),
        target=RasterTarget(50, 50, 203, media_color="yellow"),
        scaling=ScalingPolicy.FIT,
        content_optimize=ContentOptimize.GRAPHICS,
        dither=DitherMode.NONE,
    )
    assert prepared.monochrome.size == (400, 400)
    with Image.open(io.BytesIO(prepared.preview_png)) as preview:
        assert preview.size == (400, 400)
        assert preview.getpixel((0, 0)) == (255, 255, 0)


def test_zpl_graphic_uses_black_bits_and_native_target_size() -> None:
    prepared = prepare_raster_page(
        RasterPageSource(_png(size=(8, 1)), "image/png", 25.4, 3.175),
        target=RasterTarget(25.4, 3.175, 8),
        scaling=ScalingPolicy.FIT,
        dither=DitherMode.NONE,
    )
    zpl = encode_zpl_graphic(prepared)
    assert "^PW8" in zpl
    assert "^LL1" in zpl
    assert "^GFA,1,1,1,FF" in zpl


def test_portable_graymap_from_ipp_uses_the_same_raster_pipeline() -> None:
    pgm = b"P5\n2 1\n255\n\x00\xff"
    prepared = prepare_raster_page(
        RasterPageSource(pgm, "image/x-portable-graymap", 2, 1),
        target=RasterTarget(2, 1, 25.4),
        scaling=ScalingPolicy.FIT,
        dither=DitherMode.NONE,
    )
    assert prepared.monochrome.size == (2, 1)
    assert list(prepared.monochrome.getdata()) == [0, 255]


def test_source_pixel_limit_is_checked_before_decoding(monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_RASTER_MAX_SOURCE_PIXELS", "50")
    with pytest.raises(ValueError, match="raster limit"):
        prepare_raster_page(
            RasterPageSource(_png(size=(10, 10)), "image/png", 50, 50),
            target=RasterTarget(50, 50, 203),
            scaling=ScalingPolicy.FIT,
        )


def test_adapter_selection_is_explicit_and_future_driver_safe() -> None:
    printer = {"driver": "zpl", "connection": {"protocol": "raw9100"}}
    assert isinstance(raster_driver_for(printer), ZplRasterDriver)
    assert backend_for(printer).__class__.__name__ == "ZplBackend"
    with pytest.raises(ValueError, match="niimbot_b1"):
        raster_driver_for({"driver": "niimbot_b1"})


def _printer() -> dict:
    return {
        "id": "demo",
        "driver": "zpl",
        "enabled": True,
        "connection": {"protocol": "raw9100", "host": "printer", "port": 9100},
        "media": {"loaded": {"width_mm": 50, "height_mm": 50, "color": "white"}},
        "alignment": {"dpi": 203},
        "defaults": {"copies": 1, "rotation": 0},
        "zpl": {},
    }


def test_raster_job_holds_mismatch_and_releases_with_explicit_fit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(api, "_get_printer", lambda _printer_id: _printer())
    fleet = object()
    monkeypatch.setattr(api, "_fleet", lambda: fleet)
    dispatches: list[int] = []

    def dispatch(_printer_config, prepared, *, copies, delivery_port, idempotency_key_prefix):
        dispatches.append(copies)
        assert delivery_port is fleet
        assert idempotency_key_prefix.endswith('/attempt-1')
        return DocumentDispatchResult(
            bytes_sent=123,
            previews=tuple(page.preview_png for page in prepared),
            downstream_job_ids=(),
            downstream_job_states=(),
        )

    monkeypatch.setattr(api, "dispatch_raster_document", dispatch)
    request = api.RasterPrintJobCreateRequest(
        printer_id="demo",
        pages=[
            api.RasterPageRequest(
                mime_type="image/png",
                data_base64=__import__("base64").b64encode(_png()).decode("ascii"),
                width_mm=210,
                height_mm=297,
            )
        ],
        idempotency_key="cups:42",
        origin="ipp",
    )

    held = api.create_raster_print_job(request)
    assert held.status == "held"
    assert held.warning == "Document page is 210 x 297 mm but loaded media is 50 x 50 mm"
    assert held.preview_png_base64
    assert dispatches == []

    released = api.release_print_job(
        held.id,
        api.RasterPrintJobReleaseRequest(scaling=ScalingPolicy.FIT),
    )
    assert released.status == "sent"
    assert released.bytes_sent == 123
    assert released.attempts == 2
    assert dispatches == [1]

    duplicate = api.create_raster_print_job(request)
    assert duplicate.id == held.id
    assert dispatches == [1]


def test_raster_job_rejects_invalid_base64_before_persisting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    request = api.RasterPrintJobCreateRequest(
        printer_id="demo",
        pages=[
            api.RasterPageRequest(
                mime_type="image/png",
                data_base64="not-base64!",
                width_mm=50,
                height_mm=50,
            )
        ],
    )
    with pytest.raises(api.HTTPException) as exc:
        api.create_raster_print_job(request)
    assert exc.value.status_code == 400
