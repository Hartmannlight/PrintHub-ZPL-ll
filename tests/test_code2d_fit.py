from __future__ import annotations

import re

import pytest

from zplgrid import LabelTarget, compile_zpl
from zplgrid.exceptions import CompilationError
from zplgrid.units import clamp_int, mm_to_dots
from zplgrid.zpl_2d import QrCodeZplBuilder


def _base_template(element: dict) -> dict:
    return {
        "schema_version": 1,
        "name": "code2d_fit",
        "defaults": {"leaf_padding_mm": [0.0, 0.0, 0.0, 0.0]},
        "layout": {"kind": "leaf", "elements": [element]},
    }


def test_qr_size_mode_max_uses_largest_magnification_and_alignment() -> None:
    target = LabelTarget(width_mm=20.0, height_mm=20.0, dpi=203)
    template = _base_template(
        {
            "type": "qr",
            "data": "1234",
            "size_mode": "max",
            "align_h": "left",
            "align_v": "top",
        }
    )

    zpl = compile_zpl(template, target=target, variables={}, debug=False)

    sym_base = QrCodeZplBuilder(magnification=1, ecc="M", model=2, orientation="N").build("1234", x=0, y=0)
    inner_size = min(mm_to_dots(20.0, 203), mm_to_dots(20.0, 203))
    expected_size = max(sym_base.size_dots.symbol_width, sym_base.size_dots.symbol_height)
    expected_mag = clamp_int(inner_size // expected_size, 1, 10)

    match = re.search(r"\^FO(\d+),(\d+)\n\^BQN,2,(\d+)", zpl)
    assert match is not None
    x, y, mag = (int(group) for group in match.groups())
    assert (x, y) == (0, 0)
    assert mag == expected_mag


def test_qr_alignment_accounts_for_ink_offset() -> None:
    target = LabelTarget(width_mm=20.0, height_mm=20.0, dpi=203)
    template = {
        "schema_version": 1,
        "name": "qr_ink_offset",
        "layout": {
            "kind": "leaf",
            "padding_mm": [2.0, 0.0, 0.0, 0.0],
            "elements": [
                {
                    "type": "qr",
                    "data": "1234",
                    "magnification": 2,
                    "align_h": "left",
                    "align_v": "top",
                    "quiet_zone_mm": 0.0,
                }
            ],
        },
    }

    zpl = compile_zpl(template, target=target, variables={}, debug=False)

    inner_y = mm_to_dots(2.0, 203)
    expected_y = inner_y

    match = re.search(r"\^FO(\d+),(\d+)\n\^BQN,2,2", zpl)
    assert match is not None
    _, y = (int(group) for group in match.groups())
    assert y == expected_y


def test_datamatrix_size_mode_max_aligns_right_bottom() -> None:
    target = LabelTarget(width_mm=30.0, height_mm=20.0, dpi=203)
    template = _base_template(
        {
            "type": "datamatrix",
            "data": "ABC123",
            "size_mode": "max",
            "columns": 12,
            "rows": 10,
            "align_h": "right",
            "align_v": "bottom",
        }
    )

    zpl = compile_zpl(template, target=target, variables={}, debug=False)

    inner_w = mm_to_dots(30.0, 203)
    inner_h = mm_to_dots(20.0, 203)
    module = min(inner_w // 12, inner_h // 10)
    size_w = 12 * module
    size_h = 10 * module
    expected_x = inner_w - size_w
    expected_y = inner_h - size_h

    match = re.search(r"\^FO(\d+),(\d+)\n\^BXN,(\d+),", zpl)
    assert match is not None
    x, y, module_out = (int(group) for group in match.groups())
    assert (x, y) == (expected_x, expected_y)
    assert module_out == module


def test_datamatrix_size_mode_max_requires_rows_and_columns() -> None:
    target = LabelTarget(width_mm=30.0, height_mm=20.0, dpi=203)
    template = _base_template(
        {
            "type": "datamatrix",
            "data": "ABC123",
            "size_mode": "max",
        }
    )

    with pytest.raises(CompilationError):
        compile_zpl(template, target=target, variables={}, debug=False)
