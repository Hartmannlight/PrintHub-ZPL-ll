from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
import pytest

from zplgrid import LabelTarget
from zplgrid.compiler import Compiler
from zplgrid.labelary import lint_labelary_zpl, render_labelary_png
from zplgrid.measure import ZplMeasuredTextMeasurer
from zplgrid.parser import load_template


pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "tests" / "_renders" / "text-layout-matrix"


@dataclass(frozen=True)
class RenderCase:
    name: str
    text: str
    fit: str
    wrap: str
    max_lines: int
    align_h: str = "left"
    align_v: str = "center"
    width_mm: float = 74
    height_mm: float = 22
    dpi: int = 203
    font_height_mm: float = 4


CASES = (
    RenderCase(
        "reported_center_shrink_word",
        "0 Nathaniel aaaaaaaaaaaaaaaaaaa ddddddddddddd",
        "shrink_to_fit", "word", 2, "center", "center",
    ),
    RenderCase("char_A_center", "A" * 50, "wrap", "char", 2, "center", "top"),
    RenderCase("word_single_A_center", "A" * 50, "wrap", "word", 2, "center", "top"),
    RenderCase("char_i_right", "i" * 80, "wrap", "char", 3, "right", "center"),
    RenderCase("char_W_center", "W" * 40, "wrap", "char", 3, "center", "bottom"),
    RenderCase(
        "word_repeated_spaces",
        "  Alpha   bravo      charlie delta  ",
        "wrap", "word", 2, "left", "top",
    ),
    RenderCase(
        "explicit_blank_and_trailing_line",
        "ONE\n\nTHREE\n",
        "wrap", "word", 5, "center", "center",
    ),
    RenderCase(
        "truncate_two_lines",
        "one two three four five six seven eight nine ten " * 3,
        "truncate", "word", 2, "center", "bottom",
    ),
    RenderCase(
        "shrink_W_char_right",
        "W" * 75,
        "shrink_to_fit", "char", 2, "right", "center",
    ),
    RenderCase(
        "tiny_box_char",
        "Wim-123",
        "wrap", "char", 2, "center", "center", 8, 4, 203, 4,
    ),
    RenderCase(
        "utf8_and_zpl_specials_300dpi",
        "Müller & Söhne – Größe 123 € ^ ~ _ \\ /",
        "shrink_to_fit", "word", 2, "center", "center", 74, 22, 300, 4,
    ),
    RenderCase(
        "reported_center_600dpi",
        "0 Nathaniel aaaaaaaaaaaaaaaaaaa ddddddddddddd",
        "shrink_to_fit", "word", 2, "center", "center", 74, 22, 600, 4,
    ),
)

EXPECTED_VISIBLE_LINES = {
    "reported_center_shrink_word": 2,
    "char_A_center": 2,
    "word_single_A_center": 1,
    "char_i_right": 2,
    "char_W_center": 2,
    "word_repeated_spaces": 1,
    "explicit_blank_and_trailing_line": 2,
    "truncate_two_lines": 2,
    "shrink_W_char_right": 2,
    "tiny_box_char": 1,
    "utf8_and_zpl_specials_300dpi": 2,
    "reported_center_600dpi": 2,
}


def _template(case: RenderCase) -> dict:
    return {
        "schema_version": 1,
        "name": case.name,
        "defaults": {
            "leaf_padding_mm": [0.5, 0.5, 0.5, 0.5],
            "render": {"emit_ci28": True},
        },
        "layout": {
            "kind": "leaf",
            "alias": "matrix",
            "elements": [{
                "id": case.name,
                "type": "text",
                "text": case.text,
                "font_height_mm": case.font_height_mm,
                "fit": case.fit,
                "wrap": case.wrap,
                "max_lines": case.max_lines,
                "align_h": case.align_h,
                "align_v": case.align_v,
            }],
        },
    }


def _contact_sheet(paths: list[tuple[RenderCase, Path]], output: Path) -> None:
    tiles: list[Image.Image] = []
    for case, path in paths:
        image = Image.open(path).convert("RGB")
        image.thumbnail((592, 220))
        tile = Image.new("RGB", (612, 260), "#e5e7eb")
        x = (tile.width - image.width) // 2
        tile.paste(ImageOps.expand(image, border=1, fill="black"), (x, 28))
        ImageDraw.Draw(tile).text((10, 7), case.name, fill="black")
        tiles.append(tile)

    columns = 2
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 612, rows * 260), "white")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % columns) * 612, (index // columns) * 260))
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def _ink_line_boxes(path: Path) -> list[tuple[int, int, int, int]]:
    image = Image.open(path).convert("L")
    pixels = image.load()
    active_rows = [
        y for y in range(image.height)
        if any(pixels[x, y] < 200 for x in range(image.width))
    ]
    bands: list[list[int]] = []
    for y in active_rows:
        if not bands or y > bands[-1][-1] + 2:
            bands.append([y])
        else:
            bands[-1].append(y)

    boxes: list[tuple[int, int, int, int]] = []
    for band in bands:
        xs = [
            x for y in band for x in range(image.width)
            if pixels[x, y] < 200
        ]
        boxes.append((min(xs), band[0], max(xs) + 1, band[-1] + 1))
    return boxes


def test_text_layout_matrix_renders_without_labelary_linter_warnings() -> None:
    if os.getenv("LABELARY_ENABLE", "0") != "1":
        pytest.skip("Set LABELARY_ENABLE=1 to run Labelary integration tests")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    compiler = Compiler(text_measurer=ZplMeasuredTextMeasurer(enable_network=False))
    rendered: list[tuple[RenderCase, Path]] = []

    for case in CASES:
        target = LabelTarget(case.width_mm, case.height_mm, case.dpi)
        result = compiler.compile_with_diagnostics(
            load_template(_template(case)),
            target=target,
            variables={},
        )
        dpmm = int(round(case.dpi / 25.4))
        warnings = lint_labelary_zpl(
            result.zpl,
            dpmm=dpmm,
            label_width_in=case.width_mm / 25.4,
            label_height_in=case.height_mm / 25.4,
        )
        # Labelary reports expected clipping for deliberate height-overflow
        # cases and has a one-dot ^PW rounding discrepancy on very small
        # labels. It must never report the dangerous ^FB inline overwrite that
        # motivated these tests.
        assert not any("overlapping text" in warning.message for warning in warnings), (
            case.name, warnings, result.zpl,
        )
        allowed_warning_fragments = (
            "greater than maximum value",
            "field will not be visible",
        )
        assert all(
            any(fragment in warning.message for fragment in allowed_warning_fragments)
            for warning in warnings
        ), (case.name, warnings, result.zpl)

        output = OUTPUT_DIR / f"{case.name}.png"
        render_labelary_png(
            result.zpl,
            output,
            dpmm=dpmm,
            label_width_in=case.width_mm / 25.4,
            label_height_in=case.height_mm / 25.4,
        )
        assert output.stat().st_size > 0
        boxes = _ink_line_boxes(output)
        assert len(boxes) == EXPECTED_VISIBLE_LINES[case.name], (case.name, boxes)

        image_width = Image.open(output).width
        if case.align_h == "center" and case.name not in {
            "tiny_box_char",
            # Underscore ink sits below the ordinary glyph band, so generic
            # row-band segmentation cannot assign it to the correct text line.
            "utf8_and_zpl_specials_300dpi",
        }:
            center_tolerance = max(3, round(case.dpi / 100))
            for left, _top, right, _bottom in boxes:
                ink_center = (left + right) / 2
                assert abs(ink_center - image_width / 2) <= center_tolerance, (
                    case.name, boxes, image_width,
                )
        if case.align_h == "right":
            # The glyph ink itself has a small right-side bearing inside the
            # correctly aligned field; account for it in addition to padding.
            right_tolerance = max(10, round(case.dpi / 50))
            assert all(image_width - right <= right_tolerance for _left, _top, right, _bottom in boxes), (
                case.name, boxes, image_width,
            )
        rendered.append((case, output))

    _contact_sheet(rendered, OUTPUT_DIR / "contact-sheet.png")
