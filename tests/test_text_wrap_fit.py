from __future__ import annotations

import re

from zplgrid import LabelTarget
from zplgrid.compiler import Compiler
from zplgrid.measure import TextMetrics, ZplMeasuredTextMeasurer
from zplgrid.parser import load_template


class FakeMeasuredTextMeasurer(ZplMeasuredTextMeasurer):
    def __init__(self, lines_by_wrap: dict[str, list[str]]) -> None:
        self._lines_by_wrap = lines_by_wrap

    def for_dpi(self, dpi: int) -> "FakeMeasuredTextMeasurer":
        return self

    def wrap_lines(
        self,
        *,
        text: str,
        box_width_dots: int,
        font_height_dots: int,
        font_width_dots: int,
        wrap: str,
    ) -> list[str]:
        return list(self._lines_by_wrap.get(wrap, [text]))

    def measure_wrapped(
        self,
        *,
        lines: list[str],
        font_height_dots: int,
        font_width_dots: int,
        line_spacing_dots: int,
    ) -> TextMetrics:
        height = len(lines) * max(1, font_height_dots)
        return TextMetrics(lines=len(lines), width_dots=10, height_dots=height)

    def estimate(
        self,
        *,
        text: str,
        box_width_dots: int,
        font_height_dots: int,
        font_width_dots: int,
        wrap: str,
        line_spacing_dots: int,
    ) -> TextMetrics:
        lines = self.wrap_lines(
            text=text,
            box_width_dots=box_width_dots,
            font_height_dots=font_height_dots,
            font_width_dots=font_width_dots,
            wrap=wrap,
        )
        return self.measure_wrapped(
            lines=lines,
            font_height_dots=font_height_dots,
            font_width_dots=font_width_dots,
            line_spacing_dots=line_spacing_dots,
        )


def _compile_with_measurer(template: dict, measurer: FakeMeasuredTextMeasurer) -> str:
    target = LabelTarget(width_mm=50.0, height_mm=20.0, dpi=203)
    compiler = Compiler(text_measurer=measurer)
    tmpl = load_template(template)
    return compiler.compile(tmpl, target=target, variables={}, debug=False)


def test_wrap_word_inserts_line_breaks() -> None:
    measurer = FakeMeasuredTextMeasurer(
        {
            "word": ["ONE", "TWO", "THREE"],
            "char": ["O", "N", "E"],
            "none": ["RAW"],
        }
    )
    template = {
        "schema_version": 1,
        "name": "wrap_word",
        "layout": {
            "kind": "leaf",
            "elements": [
                {"type": "text", "text": "ignore", "wrap": "word", "fit": "wrap"},
            ],
        },
    }
    zpl = _compile_with_measurer(template, measurer)
    assert "^FDONE\\&TWO\\&THREE" in zpl


def test_wrap_char_inserts_char_breaks() -> None:
    measurer = FakeMeasuredTextMeasurer(
        {
            "word": ["WORD"],
            "char": ["A", "B", "C"],
            "none": ["RAW"],
        }
    )
    template = {
        "schema_version": 1,
        "name": "wrap_char",
        "layout": {
            "kind": "leaf",
            "elements": [
                {"type": "text", "text": "ignore", "wrap": "char", "fit": "wrap"},
            ],
        },
    }
    zpl = _compile_with_measurer(template, measurer)
    assert "^FD" in zpl
    assert "A\\&B\\&C" in zpl


def test_fit_wrap_preserves_all_lines_but_respects_max_lines_in_fb() -> None:
    measurer = FakeMeasuredTextMeasurer(
        {"word": ["L1", "L2", "L3"]}
    )
    template = {
        "schema_version": 1,
        "name": "fit_wrap_max",
        "layout": {
            "kind": "leaf",
            "elements": [
                {"type": "text", "text": "ignore", "wrap": "word", "fit": "wrap", "max_lines": 2},
            ],
        },
    }
    zpl = _compile_with_measurer(template, measurer)
    assert "^FDL1\\&L2\\&L3" in zpl
    assert re.search(r"\^FB\d+,2,", zpl) is not None


def test_fit_truncate_limits_lines() -> None:
    measurer = FakeMeasuredTextMeasurer(
        {"word": ["L1", "L2", "L3"]}
    )
    template = {
        "schema_version": 1,
        "name": "fit_truncate",
        "layout": {
            "kind": "leaf",
            "elements": [
                {"type": "text", "text": "ignore", "wrap": "word", "fit": "truncate", "max_lines": 2},
            ],
        },
    }
    zpl = _compile_with_measurer(template, measurer)
    assert "^FDL1\\&L2" in zpl
    assert "L3" not in zpl
    assert re.search(r"\^FB\d+,2,", zpl) is not None


def test_fit_overflow_with_wrap_none_emits_no_fb() -> None:
    measurer = FakeMeasuredTextMeasurer({"none": ["RAW"]})
    template = {
        "schema_version": 1,
        "name": "fit_overflow",
        "layout": {
            "kind": "leaf",
            "elements": [
                {"type": "text", "text": "raw", "wrap": "none", "fit": "overflow"},
            ],
        },
    }
    zpl = _compile_with_measurer(template, measurer)
    assert "^FB" not in zpl
