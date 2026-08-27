from __future__ import annotations

import itertools
import re

from zplgrid import LabelTarget
from zplgrid.compiler import Compiler
from zplgrid.measure import ZplMeasuredTextMeasurer
from zplgrid.parser import load_template


TEXTS = (
    "",
    "short",
    "Alpha bravo charlie delta echo foxtrot",
    "W" * 40,
    "i" * 80,
    "a" * 30 + " " + "W" * 20,
    "  repeated   whitespace  ",
    "ONE\nTWO\nTHREE",
    "ONE\n\nTHREE\n",
    "ONE\r\nTWO\rTHREE",
    r"literal\nline",
    "^caret ~tilde _underscore \\slash & ampersand",
    "Müller & Söhne – Größe 123 €",
    "🙂🙂🙂 unknown glyph width",
)

FIT_WRAP_PAIRS = (
    ("overflow", "none"),
    ("wrap", "word"),
    ("wrap", "char"),
    ("truncate", "word"),
    ("truncate", "char"),
    ("shrink_to_fit", "word"),
    ("shrink_to_fit", "char"),
)

TARGETS = (
    LabelTarget(width_mm=8, height_mm=4, dpi=203),
    LabelTarget(width_mm=40, height_mm=20, dpi=300),
    LabelTarget(width_mm=74, height_mm=26, dpi=600),
)


def _template(text: str, fit: str, wrap: str, max_lines: int, align_h: str, align_v: str) -> dict:
    return {
        "schema_version": 1,
        "name": "text-layout-matrix",
        "defaults": {
            "leaf_padding_mm": [0.5, 0.5, 0.5, 0.5],
            "render": {"emit_ci28": True},
        },
        "layout": {
            "kind": "leaf",
            "elements": [{
                "type": "text",
                "text": text,
                "font_height_mm": 4,
                "fit": fit,
                "wrap": wrap,
                "max_lines": max_lines,
                "align_h": align_h,
                "align_v": align_v,
            }],
        },
    }


def test_text_layout_state_space_never_emits_unsafe_field_blocks() -> None:
    compiler = Compiler(text_measurer=ZplMeasuredTextMeasurer(enable_network=False))
    diagnostic_codes = {
        "text_max_lines_exceeded",
        "text_truncated",
        "text_cannot_fit",
        "text_height_overflow",
        "text_width_overflow",
        "text_unsupported_glyph",
        "text_utf8_disabled",
    }

    cases = itertools.product(
        TEXTS,
        FIT_WRAP_PAIRS,
        (1, 2, 5),
        ("left", "center", "right"),
        ("top", "center", "bottom"),
        TARGETS,
    )
    for text, (fit, wrap), max_lines, align_h, align_v, target in cases:
        result = compiler.compile_with_diagnostics(
            load_template(_template(text, fit, wrap, max_lines, align_h, align_v)),
            target=target,
            variables={},
        )

        assert result.zpl.startswith("^XA\n")
        assert result.zpl.endswith("^XZ\n")
        assert "^FO-" not in result.zpl
        assert all(int(value) == 1 for value in re.findall(r"\^FB\d+,(\d+),", result.zpl))
        if align_h == "left":
            assert "^FB" not in result.zpl
        assert {item.code for item in result.diagnostics} <= diagnostic_codes


def test_truncate_never_emits_more_than_max_lines() -> None:
    compiler = Compiler(text_measurer=ZplMeasuredTextMeasurer(enable_network=False))
    for wrap, max_lines in itertools.product(("word", "char"), (1, 2, 5)):
        result = compiler.compile_with_diagnostics(
            load_template(_template("word " * 100, "truncate", wrap, max_lines, "left", "top")),
            target=LabelTarget(width_mm=30, height_mm=20, dpi=203),
            variables={},
        )
        assert result.zpl.count("^A0N") <= max_lines
        assert any(item.code == "text_truncated" for item in result.diagnostics)
