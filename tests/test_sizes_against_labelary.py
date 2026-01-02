from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from zplgrid import LabelTarget, compile_zpl
from zplgrid.labelary import render_labelary_png
from zplgrid.units import mm_to_dots
from zplgrid.zpl_2d import DataMatrixZplBuilder, QrCodeZplBuilder

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABEL_DPI = 203
LABEL_WIDTH_IN = 4.0
LABEL_HEIGHT_IN = 6.0
LABEL_WIDTH_MM = LABEL_WIDTH_IN * 25.4
LABEL_HEIGHT_MM = LABEL_HEIGHT_IN * 25.4


def _measure_ink_bbox(png_path: Path, threshold: int = 250) -> tuple[int, int, int, int]:
    img = Image.open(png_path).convert('L')
    w, h = img.size
    px = img.load()

    min_x, min_y = w, h
    max_x, max_y = -1, -1

    for y in range(h):
        for x in range(w):
            if px[x, y] < threshold:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

    if max_x < 0:
        raise AssertionError('No ink detected in image; did the barcode render?')

    width = max_x - min_x + 1
    height = max_y - min_y + 1
    return min_x, min_y, width, height


def _render_compiled_label(zpl: str, output_name: str) -> Path:
    out_dir = PROJECT_ROOT / 'tests' / '_renders'
    out = out_dir / output_name
    render_labelary_png(
        zpl,
        out,
        dpmm=8,
        label_width_in=LABEL_WIDTH_IN,
        label_height_in=LABEL_HEIGHT_IN,
    )
    return out


def _compile_single_element_template(element: dict) -> str:
    template = {
        "schema_version": 1,
        "name": "size_check",
        "defaults": {
            "leaf_padding_mm": [0.0, 0.0, 0.0, 0.0],
            "render": {"missing_variables": "error", "emit_ci28": False},
        },
        "layout": {"kind": "leaf", "elements": [element]},
    }
    target = LabelTarget(width_mm=LABEL_WIDTH_MM, height_mm=LABEL_HEIGHT_MM, dpi=LABEL_DPI)
    return compile_zpl(template, target=target, variables={}, debug=False)


@pytest.mark.parametrize(
    'data,magnification,ecc',
    [
        ('HELLO-QR-1234567890', 6, 'Q'),
        ('SHORT', 3, 'M'),
        ('QR-EXTENDED-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ', 4, 'L'),
        ('QR2@1', 2, 'H'),
        ('MID-1234', 5, 'M'),
        ('QR-WIDE-HELLO-WORLD-1234567890-EXTRA-ABCDE-XYZ1234', 8, 'Q'),
        ('ALNUM-1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ', 4, 'H'),
        ('ALNUM-EXTRA-1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ', 3, 'L'),
        ('PAYLOAD-ALNUM-ONE-2345678901ABCDE', 5, 'Q'),
        ('PAYLOAD-ALNUM-TWO-ABCDE12345FGHIJ', 6, 'M'),
        ('PAYLOAD-ALNUM-THREE-ABCDE12345FGHIJKLMNOP', 7, 'H'),
        ('PAYLOAD-ALNUM-LONG-1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890', 4, 'L'),
    ],
)
def test_qr_ink_size_and_offset_match_labelary_bbox(
    data: str,
    magnification: int,
    ecc: str,
) -> None:
    if os.getenv('LABELARY_ENABLE', '0') != '1':
        pytest.skip('Set LABELARY_ENABLE=1 to run Labelary integration tests')

    b = QrCodeZplBuilder(magnification=magnification, ecc=ecc, model=2, orientation='N')
    sym = b.build(data, x=0, y=0)

    out_dir = PROJECT_ROOT / 'tests' / '_renders'
    out = out_dir / f'qr_v{sym.meta["version"]}_mag{magnification}_ecc{ecc}.png'
    render_labelary_png(sym.zpl, out, dpmm=8, label_width_in=4.0, label_height_in=6.0)

    min_x, min_y, ink_w, ink_h = _measure_ink_bbox(out)

    assert ink_w == sym.ink.ink_width
    assert ink_h == sym.ink.ink_height
    assert min_x == sym.ink.ink_offset_x
    assert min_y == sym.ink.ink_offset_y


@pytest.mark.parametrize(
    'name,data,magnification,ecc,input_mode,character_mode,quiet_zone_mm',
    [
        ('qr_auto_short', 'HELLO-123', 3, 'M', 'A', None, 0.0),
        ('qr_auto_long', 'HELLO-WORLD-1234567890-ABCDEFG', 4, 'Q', 'A', None, 1.0),
        ('qr_manual_numeric', '123456789012345678901234', 6, 'H', 'M', 'N', 0.0),
        ('qr_manual_alnum', 'ALNUM-1234567890ABCDE', 5, 'L', 'M', 'A', 0.5),
        ('qr_auto_byte', 'Byte-mode-lowercase-12345', 2, 'M', 'A', None, 0.0),
    ],
)
def test_compiler_qr_size_matches_labelary_bbox(
    name: str,
    data: str,
    magnification: int,
    ecc: str,
    input_mode: str,
    character_mode: str | None,
    quiet_zone_mm: float,
) -> None:
    if os.getenv('LABELARY_ENABLE', '0') != '1':
        pytest.skip('Set LABELARY_ENABLE=1 to run Labelary integration tests')

    element = {
        "type": "qr",
        "data": data,
        "magnification": magnification,
        "error_correction": ecc,
        "input_mode": input_mode,
        "quiet_zone_mm": quiet_zone_mm,
    }
    if character_mode is not None:
        element["character_mode"] = character_mode

    zpl = _compile_single_element_template(element)
    out = _render_compiled_label(zpl, f'{name}.png')
    _, _, ink_w, ink_h = _measure_ink_bbox(out)

    sym = QrCodeZplBuilder(
        magnification=magnification,
        ecc=ecc,
        model=2,
        orientation='N',
    ).build(data, x=0, y=0)

    assert ink_w == sym.ink.ink_width
    assert ink_h == sym.ink.ink_height


@pytest.mark.parametrize(
    'data,module_size,columns,rows,escape_char',
    [
        ('DM-TEST-1234', 5, 24, 24, '|'),
        ('DM1', 4, 16, 16, '!'),
        ('DM-LONGER-0123456789', 6, 32, 32, '~'),
        ('DM-MID-ABCDE12345', 3, 20, 20, '#'),
        ('DM', 2, 10, 10, '%'),
        ('DM-LARGE-1234567890', 8, 36, 36, '^'),
    ],
)
def test_datamatrix_ink_size_and_offset_match_labelary_bbox(
    data: str,
    module_size: int,
    columns: int,
    rows: int,
    escape_char: str,
) -> None:
    if os.getenv('LABELARY_ENABLE', '0') != '1':
        pytest.skip('Set LABELARY_ENABLE=1 to run Labelary integration tests')

    b = DataMatrixZplBuilder(
        module_size=module_size,
        columns=columns,
        rows=rows,
        escape_char=escape_char,
    )
    sym = b.build(data, x=0, y=0)

    out_dir = PROJECT_ROOT / 'tests' / '_renders'
    out = out_dir / f'datamatrix_{columns}x{rows}_h{module_size}.png'
    render_labelary_png(sym.zpl, out, dpmm=8, label_width_in=4.0, label_height_in=6.0)

    min_x, min_y, ink_w, ink_h = _measure_ink_bbox(out)

    assert ink_w == sym.ink.ink_width
    assert ink_h == sym.ink.ink_height
    assert min_x == sym.ink.ink_offset_x
    assert min_y == sym.ink.ink_offset_y


@pytest.mark.parametrize(
    'name,data,module_size_mm,columns,rows,quality,format_id,escape_char,quiet_zone_mm',
    [
        ('dm_small', 'DM-TEST-1234', 0.6, 16, 16, 200, 6, '!', 0.0),
        ('dm_medium', 'DM-LONGER-0123456789', 0.8, 24, 24, 200, 6, '#', 0.5),
        ('dm_large', 'DM-LARGE-1234567890', 1.0, 32, 32, 200, 6, '$', 0.0),
        ('dm_format_0', 'DM-FORMAT-0', 0.6, 18, 18, 200, 0, '&', 0.0),
    ],
)
def test_compiler_datamatrix_size_matches_labelary_bbox(
    name: str,
    data: str,
    module_size_mm: float,
    columns: int,
    rows: int,
    quality: int,
    format_id: int,
    escape_char: str,
    quiet_zone_mm: float,
) -> None:
    if os.getenv('LABELARY_ENABLE', '0') != '1':
        pytest.skip('Set LABELARY_ENABLE=1 to run Labelary integration tests')

    element = {
        "type": "datamatrix",
        "data": data,
        "module_size_mm": module_size_mm,
        "columns": columns,
        "rows": rows,
        "quality": quality,
        "format_id": format_id,
        "escape_char": escape_char,
        "quiet_zone_mm": quiet_zone_mm,
    }

    zpl = _compile_single_element_template(element)
    out = _render_compiled_label(zpl, f'{name}.png')
    _, _, ink_w, ink_h = _measure_ink_bbox(out)

    module_size = max(1, mm_to_dots(module_size_mm, LABEL_DPI))
    sym = DataMatrixZplBuilder(
        module_size=module_size,
        columns=columns,
        rows=rows,
        quality=quality,
        escape_char=escape_char,
    ).build(data, x=0, y=0)

    assert ink_w == sym.ink.ink_width
    assert ink_h == sym.ink.ink_height
