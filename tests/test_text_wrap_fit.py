from __future__ import annotations

import string

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


def _compile_result(template: dict, measurer: FakeMeasuredTextMeasurer):
    target = LabelTarget(width_mm=50.0, height_mm=20.0, dpi=203)
    compiler = Compiler(text_measurer=measurer)
    tmpl = load_template(template)
    return compiler.compile_with_diagnostics(tmpl, target=target, variables={}, debug=False)


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
    assert "^FDONE" in zpl
    assert "^FDTWO" in zpl
    assert "^FDTHREE" in zpl
    assert "^FB" not in zpl


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
    assert "^FDA" in zpl
    assert "^FDB" in zpl
    assert "^FDC" in zpl
    assert "^FB" not in zpl


def test_fit_wrap_preserves_all_lines_and_reports_max_lines_overflow() -> None:
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
    result = _compile_result(template, measurer)
    assert "^FDL1" in result.zpl
    assert "^FDL2" in result.zpl
    assert "^FDL3" in result.zpl
    assert "^FB" not in result.zpl
    assert [item.code for item in result.diagnostics] == ["text_max_lines_exceeded"]


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
    assert "^FDL1" in zpl
    assert "^FDL2" in zpl
    assert "L3" not in zpl
    assert "^FB" not in zpl


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


def test_centered_lines_use_independent_single_line_field_blocks() -> None:
    measurer = FakeMeasuredTextMeasurer({"word": ["FIRST", "SECOND"]})
    template = {
        "schema_version": 1,
        "name": "centered_lines",
        "layout": {
            "kind": "leaf",
            "elements": [{
                "type": "text",
                "text": "ignore",
                "wrap": "word",
                "fit": "shrink_to_fit",
                "max_lines": 2,
                "align_h": "center",
            }],
        },
    }

    zpl = _compile_with_measurer(template, measurer)

    assert zpl.count("^FB") == 2
    assert zpl.count(",1,0,C,0") == 2
    assert "^FDFIRST\\&" in zpl
    assert "^FDSECOND\\&" in zpl


def test_offline_font_metrics_distinguish_wide_and_narrow_glyphs() -> None:
    measurer = ZplMeasuredTextMeasurer(enable_network=False)

    wide = measurer._line_width("W" * 20, 32, 32)
    normal = measurer._line_width("a" * 20, 32, 32)
    narrow = measurer._line_width("i" * 20, 32, 32)

    assert wide > normal > narrow
    assert wide > 500
    assert narrow < 220


def test_offline_font_tables_cover_printable_ascii_without_duplicates() -> None:
    expected = set(string.printable[:95])
    for groups in (
        ZplMeasuredTextMeasurer._FALLBACK_GLYPH_WIDTH_GROUPS,
        ZplMeasuredTextMeasurer._TINY_FALLBACK_GLYPH_WIDTH_GROUPS,
    ):
        chars = "".join(group for group, _ratio in groups)
        assert expected <= set(chars)
        assert len(chars) == len(set(chars))


def test_compiler_uses_deterministic_offline_measurement_by_default(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LABELARY_ENABLE", "1")

    compiler = Compiler()

    assert isinstance(compiler.text_measurer, ZplMeasuredTextMeasurer)
    assert compiler.text_measurer._enable_network is False


def test_offline_char_wrap_never_leaves_an_oversized_wide_glyph_line() -> None:
    measurer = ZplMeasuredTextMeasurer(enable_network=False)
    lines = measurer.wrap_lines(
        text="W" * 30,
        box_width_dots=300,
        font_height_dots=32,
        font_width_dots=32,
        wrap="char",
    )

    assert len(lines) > 1
    assert all(measurer._line_width(line, 32, 32) <= 300 for line in lines)


def test_char_wrap_accounts_for_the_hyphens_own_width() -> None:
    measurer = ZplMeasuredTextMeasurer(enable_network=False)
    lines = measurer.wrap_lines(
        text="i" * 50,
        box_width_dots=30,
        font_height_dots=32,
        font_width_dots=32,
        wrap="char",
    )

    assert len(lines) > 1
    assert all(measurer._line_width(line, 32, 32) <= 30 for line in lines)
    assert "".join(line.removesuffix("-") for line in lines) == "i" * 50


def test_offline_metrics_use_more_conservative_ratios_for_tiny_fonts() -> None:
    measurer = ZplMeasuredTextMeasurer(enable_network=False)

    assert measurer._line_width("-" * 20, 8, 8) >= 179
    assert measurer._line_width("W" * 20, 8, 8) >= 162
    assert measurer._line_width("m" * 20, 8, 8) >= 151


def test_unreliable_builtin_font_glyphs_are_reported() -> None:
    template = {
        "schema_version": 1,
        "defaults": {
            "leaf_padding_mm": [0, 0, 0, 0],
            "render": {"emit_ci28": True},
        },
        "layout": {
            "kind": "leaf",
            "elements": [{
                "type": "text",
                "text": "backslash \\ and emoji 🙂",
                "fit": "wrap",
                "wrap": "word",
                "max_lines": 2,
            }],
        },
    }
    result = Compiler(
        text_measurer=ZplMeasuredTextMeasurer(enable_network=False),
    ).compile_with_diagnostics(
        load_template(template),
        target=LabelTarget(width_mm=74, height_mm=22, dpi=203),
        variables={},
    )

    diagnostic = next(item for item in result.diagnostics if item.code == "text_unsupported_glyph")
    assert repr("\\") in diagnostic.message
    assert repr("🙂") in diagnostic.message


def test_non_ascii_text_warns_when_ci28_is_disabled() -> None:
    template = {
        "schema_version": 1,
        "defaults": {
            "leaf_padding_mm": [0, 0, 0, 0],
            "render": {"emit_ci28": False},
        },
        "layout": {
            "kind": "leaf",
            "elements": [{
                "type": "text",
                "text": "Müller",
                "fit": "overflow",
                "wrap": "none",
            }],
        },
    }
    result = Compiler(
        text_measurer=ZplMeasuredTextMeasurer(enable_network=False),
    ).compile_with_diagnostics(
        load_template(template),
        target=LabelTarget(width_mm=74, height_mm=22, dpi=203),
        variables={},
    )

    assert any(item.code == "text_utf8_disabled" for item in result.diagnostics)


def test_shrink_to_fit_does_not_shrink_for_impossible_explicit_line_limit() -> None:
    template = {
        "schema_version": 1,
        "name": "explicit_lines",
        "defaults": {"leaf_padding_mm": [0, 0, 0, 0]},
        "layout": {
            "kind": "leaf",
            "elements": [{
                "type": "text",
                "text": "ONE\\nTWO\\nTHREE",
                "font_height_mm": 4,
                "wrap": "word",
                "fit": "shrink_to_fit",
                "max_lines": 2,
                "align_h": "left",
                "align_v": "top",
            }],
        },
    }
    target = LabelTarget(width_mm=50, height_mm=30, dpi=203)
    result = Compiler(
        text_measurer=ZplMeasuredTextMeasurer(enable_network=False),
    ).compile_with_diagnostics(load_template(template), target=target, variables={})

    assert "^A0N,32,32" in result.zpl
    assert [item.code for item in result.diagnostics] == ["text_cannot_fit"]
