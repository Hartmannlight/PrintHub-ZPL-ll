from __future__ import annotations

from typing import Any, Mapping

from zplgrid.printer_media import resolve_dynamic_printer_media
import pytest


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


def _agent_printer():
    return {**_printer(), 'connection': {'protocol': 'zebra_tamer', 'base_url':'http://agent', 'printer_id':'p'},
            'zpl': {'darkness':10, 'print_speed':3}, 'alignment': {'dpi':300, 'offset_x_mm':2, 'offset_y_mm':1}}


def test_agent_owns_media_color_resolution_and_offsets_are_not_applied_twice(monkeypatch):
    payload = {'media': {'state': {'media': {'width_mm':60, 'height_mm':30, 'color': {'name':'Yellow', 'hex':'#ffff00'}, 'print_technology':'direct_thermal'}, 'remaining_labels':77}},
               'device': {'observation': {'resolution_dpi':203}, 'profile': {}}, 'webui_enabled':True}
    monkeypatch.setattr('zplgrid.printer_media.get_configuration', lambda _: payload)
    printer = _agent_printer()
    resolved = resolve_dynamic_printer_media(printer)
    assert resolved['media']['loaded'] == {'width_mm':60, 'height_mm':30, 'color':'Yellow', 'color_hex':'#ffff00', 'type':'direct_thermal'}
    assert resolved['alignment'] == {'dpi':203, 'offset_x_mm':0, 'offset_y_mm':0}
    assert resolved['zpl'] == {}
    assert printer['alignment']['dpi'] == 300


@pytest.mark.parametrize('unavailable', [True, False])
def test_missing_agent_media_never_falls_back_to_registry_defaults(monkeypatch, unavailable):
    def read(_):
        if unavailable:
            raise RuntimeError('offline')
        return {'media': {'state':None}, 'device': {'profile': {'resolution_dpi':203}}}
    monkeypatch.setattr('zplgrid.printer_media.get_configuration', read)
    resolved = resolve_dynamic_printer_media(_agent_printer())
    assert resolved['media']['loaded'] is None
    assert resolved['media']['authority']['state'] == ('unavailable' if unavailable else 'not_configured')


def test_resolve_dynamic_printer_media_rejects_invalid_live_values() -> None:
    printer = _printer()

    def read_json(_url: str, _timeout_s: float) -> Mapping[str, Any]:
        return {"label_width_mm": 50, "label_height_mm": 0, "dpmm": 8}

    assert resolve_dynamic_printer_media(printer, read_json=read_json) == printer
