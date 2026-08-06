from __future__ import annotations

from typing import Any, Mapping

from zplgrid.printer_media import resolve_dynamic_printer_media


def _printer() -> dict[str, Any]:
    return {
        "id": "virtual-zebra",
        "media": {
            "loaded": {"width_mm": 50, "height_mm": 50, "color": "white", "type": "virtual"},
            "dynamic_source": {
                "kind": "zpl_emulator_settings",
                "url": "http://virtual-zebra:9191/api/settings",
                "timeout_ms": 750,
            },
        },
        "alignment": {"dpi": 203, "offset_x_mm": 0, "offset_y_mm": 0},
    }


def test_resolve_dynamic_printer_media_uses_live_emulator_settings() -> None:
    printer = _printer()
    calls: list[tuple[str, float]] = []

    def read_json(url: str, timeout_s: float) -> Mapping[str, Any]:
        calls.append((url, timeout_s))
        return {"label_width_mm": 50, "label_height_mm": 30, "dpmm": 8}

    resolved = resolve_dynamic_printer_media(printer, read_json=read_json)

    assert calls == [("http://virtual-zebra:9191/api/settings", 0.75)]
    assert resolved["media"]["loaded"]["width_mm"] == 50
    assert resolved["media"]["loaded"]["height_mm"] == 30
    assert resolved["alignment"]["dpi"] == 203
    assert printer["media"]["loaded"]["height_mm"] == 50


def test_resolve_dynamic_printer_media_keeps_fallback_when_source_is_unavailable() -> None:
    printer = _printer()

    def read_json(_url: str, _timeout_s: float) -> Mapping[str, Any]:
        raise OSError("emulator unavailable")

    assert resolve_dynamic_printer_media(printer, read_json=read_json) == printer


def test_resolve_dynamic_printer_media_rejects_invalid_live_values() -> None:
    printer = _printer()

    def read_json(_url: str, _timeout_s: float) -> Mapping[str, Any]:
        return {"label_width_mm": 50, "label_height_mm": 0, "dpmm": 8}

    assert resolve_dynamic_printer_media(printer, read_json=read_json) == printer
