from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from zplgrid.zpl_text_metrics import ZplFontSpec, ZplTextMeasurer

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
        raise AssertionError('No ink detected in image; did the text render?')

    width = max_x - min_x + 1
    height = max_y - min_y + 1
    return min_x, min_y, width, height


def _skip_if_labelary_disabled() -> None:
    if os.getenv('LABELARY_ENABLE', '0') != '1':
        pytest.skip('Set LABELARY_ENABLE=1 to run Labelary integration tests')


def _assert_text_ink_matches_labelary(
    text: str,
    font: ZplFontSpec,
    out_name: str,
    x: int = 0,
    y: int = 0,
    use_utf8: bool = True,
) -> None:
    m = ZplTextMeasurer(
        dpmm=8,
        label_width_in=4.0,
        label_height_in=6.0,
        threshold=250,
        use_utf8=use_utf8,
    )

    out_dir = PROJECT_ROOT / 'tests' / '_renders'
    out_dir.mkdir(parents=True, exist_ok=True)

    out = out_dir / out_name
    ink = m.measure_and_render(text=text, font=font, out_path=out, x=x, y=y)

    min_x, min_y, ink_w, ink_h = _measure_ink_bbox(out)

    assert ink_w == ink.ink_width
    assert ink_h == ink.ink_height
    assert min_x == ink.ink_offset_x
    assert min_y == ink.ink_offset_y


def test_text_ink_size_and_offset_match_labelary_bbox_ascii() -> None:
    _skip_if_labelary_disabled()

    font = ZplFontSpec(font='0', orientation='N', height=50, width=50)
    _assert_text_ink_matches_labelary(
        text='HELLO-123',
        font=font,
        out_name='text_a0n_h50_w50_hello.png',
        x=0,
        y=0,
        use_utf8=True,
    )


def test_text_ink_size_and_offset_match_labelary_bbox_with_offset() -> None:
    _skip_if_labelary_disabled()

    font = ZplFontSpec(font='0', orientation='N', height=40, width=40)
    _assert_text_ink_matches_labelary(
        text='OFFSET-TEST',
        font=font,
        out_name='text_a0n_h40_w40_offset_x120_y200.png',
        x=120,
        y=200,
        use_utf8=True,
    )


@pytest.mark.parametrize(
    'case_id,text,x,y',
    [
        ('short_ascii', 'SHORT', 0, 0),
        ('long_ascii', 'LONG-TEXT-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ', 20, 80),
        ('mixed_chars', 'A&B/C + D.E, 123', 10, 40),
        ('utf8_umlaut', 'UMLAUT ÄÖÜ', 30, 120),
    ],
)
def test_text_ink_size_and_offset_varied_content(
    case_id: str,
    text: str,
    x: int,
    y: int,
) -> None:
    _skip_if_labelary_disabled()

    font = ZplFontSpec(font='0', orientation='N', height=35, width=35)
    _assert_text_ink_matches_labelary(
        text=text,
        font=font,
        out_name=f'text_var_{case_id}_a0n_h35_w35.png',
        x=x,
        y=y,
        use_utf8=True,
    )


@pytest.mark.parametrize(
    'case_id,font',
    [
        ('font0_h20', ZplFontSpec(font='0', orientation='N', height=20, width=20)),
        ('font0_h60', ZplFontSpec(font='0', orientation='N', height=60, width=60)),
        ('fontA_h30', ZplFontSpec(font='A', orientation='N', height=30, width=30)),
        ('fontB_h40', ZplFontSpec(font='B', orientation='N', height=40, width=40)),
    ],
)
def test_text_ink_size_and_offset_varied_fonts(
    case_id: str,
    font: ZplFontSpec,
) -> None:
    _skip_if_labelary_disabled()

    _assert_text_ink_matches_labelary(
        text='FONT-TYPE-TEST',
        font=font,
        out_name=f'text_font_{case_id}.png',
        x=0,
        y=0,
        use_utf8=False,
    )


@pytest.mark.parametrize(
    'font_id,font_char',
    [
        ('0', '0'), ('1', '1'), ('2', '2'), ('3', '3'), ('4', '4'),
        ('5', '5'), ('6', '6'), ('7', '7'), ('8', '8'), ('9', '9'),
        ('A', 'A'), ('B', 'B'), ('C', 'C'), ('D', 'D'), ('E', 'E'),
        ('F', 'F'), ('G', 'G'), ('H', 'H'), ('I', 'I'), ('J', 'J'),
        ('K', 'K'), ('L', 'L'), ('M', 'M'), ('N', 'N'), ('O', 'O'),
        ('P', 'P'), ('Q', 'Q'), ('R', 'R'), ('S', 'S'), ('T', 'T'),
        ('U', 'U'), ('V', 'V'), ('W', 'W'), ('X', 'X'), ('Y', 'Y'),
        ('Z', 'Z'),
    ],
)
@pytest.mark.parametrize(
    'size,text,case_id',
    [
        (20, 'THE-QUICK-BROWN-FOX-JUMPS-OVER-1234567890', 's20'),
        (40, 'BIG-40-TEST', 's40'),
    ],
)
def test_text_ink_size_and_offset_all_default_zpl_fonts(
    font_id: str,
    font_char: str,
    size: int,
    text: str,
    case_id: str,
) -> None:
    _skip_if_labelary_disabled()

    font = ZplFontSpec(font=font_char, orientation='N', height=size, width=size)
    _assert_text_ink_matches_labelary(
        text=text,
        font=font,
        out_name=f'text_all_fonts_{font_id}_{case_id}.png',
        x=0,
        y=0,
        use_utf8=False,
    )


def test_build_zpl_utf8_hex_contains_ci28_and_fh() -> None:
    m = ZplTextMeasurer(use_utf8=True)
    font = ZplFontSpec(font='0', orientation='N', height=30, width=30)

    zpl = m.build_zpl(text='UMLAUT ÄÖÜ', font=font, x=0, y=0)

    assert '^CI28' in zpl
    assert '^FH' in zpl
    assert '_C3_84' in zpl  # Ä in UTF-8
    assert '_C3_96' in zpl  # Ö in UTF-8
    assert '_C3_9C' in zpl  # Ü in UTF-8


def test_build_zpl_ascii_without_utf8_does_not_emit_ci28_or_fh() -> None:
    m = ZplTextMeasurer(use_utf8=False)
    font = ZplFontSpec(font='0', orientation='N', height=30, width=30)

    zpl = m.build_zpl(text='ASCII-ONLY', font=font, x=0, y=0)

    assert '^CI28' not in zpl
    assert '^FH' not in zpl
    assert '^FDASCII-ONLY^FS' in zpl
