from __future__ import annotations

import io
import base64

from PIL import Image
import pytest

from zplgrid import api
from zplgrid.printing.domain import (
    ContentOptimize,
    DitherMode,
    MediaMismatchError,
    RasterPageSource,
    RasterTarget,
    ScalingPolicy,
)
from zplgrid.printing.raster import encode_prepared_raster, encode_zpl_graphic, prepare_raster_page
from zplgrid.printing.documents import _pdf_sizes, prepare_source_document
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


def test_source_image_is_interpreted_as_target_sized_document() -> None:
    pages = prepare_source_document(
        _png(), mime_type="image/png", target=RasterTarget(50, 30, 203)
    )
    assert len(pages) == 1
    assert pages[0].width_mm == 50
    assert pages[0].height_mm == 30


def test_pdf_page_dimensions_are_owned_by_document_preparation() -> None:
    sizes = _pdf_sizes(
        "Pages:           2\n"
        "Page 1 size:     141.732 x 141.732 pts\n"
        "Page 2 size:     595.276 x 841.89 pts\n"
    )
    assert sizes[0] == pytest.approx((50.0, 50.0), abs=0.01)
    assert sizes[1] == pytest.approx((210.0, 297.0), abs=0.01)


def test_prepared_raster_contract_is_device_independent() -> None:
    prepared = prepare_raster_page(
        RasterPageSource(_png(size=(8, 1)), "image/png", 25.4, 3.175),
        target=RasterTarget(25.4, 3.175, 8),
        scaling=ScalingPolicy.FIT,
        dither=DitherMode.NONE,
    )

    payload = __import__("json").loads(encode_prepared_raster(prepared, copies=2))

    assert payload == {
        "version": 1,
        "width_px": 8,
        "height_px": 1,
        "dpi": 8,
        "copies": 2,
        "black_bits_base64": "/w==",
    }


def _printer() -> dict:
    return {
        "id": "demo",
        "driver": "zpl",
        "enabled": True,
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


def test_source_document_is_persisted_then_held_by_printhub_policy(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setattr(api, "_get_printer", lambda _printer_id: _printer())
    monkeypatch.setattr(
        api,
        "prepare_source_document",
        lambda data, **_kwargs: (RasterPageSource(_png(), "image/png", 210, 297),),
    )
    request = api.DocumentPrintJobCreateRequest(
        printer_id="demo",
        mime_type="application/pdf",
        data_base64=base64.b64encode(b"%PDF-test").decode("ascii"),
        idempotency_key="ipp:document:1",
        origin="ipp",
    )

    held = api.create_document_print_job(request)

    assert held.source_kind == "document"
    assert held.status == "held"
    assert held.page_count == 1
    persisted = api.load_job_document(held.id)
    assert persisted["kind"] == "source_document"
    assert base64.b64decode(persisted["data_base64"]) == b"%PDF-test"
