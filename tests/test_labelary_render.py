from pathlib import Path

import pytest

from zplgrid import LabelTarget, compile_zpl
from zplgrid.labelary import render_labelary_png

LABEL_WIDTH_MM = 74.0
LABEL_HEIGHT_MM = 26.0
LABEL_DPI = 203

pytestmark = pytest.mark.integration

DEFAULT_VARS = {
    "name": "Widget",
    "code": "ZPLGRID-QR-01",
    "payload": "DM-TEST-01",
}


def _render_png(zpl: str, output_path: Path, *, target: LabelTarget) -> None:
    dpmm = int(round(target.dpi / 25.4))
    if dpmm not in {6, 8, 12, 24}:
        raise ValueError(f"unsupported dpmm: {dpmm}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    render_labelary_png(
        zpl=zpl,
        out_path=output_path,
        dpmm=dpmm,
        label_width_in=target.width_mm / 25.4,
        label_height_in=target.height_mm / 25.4,
    )


def _compile_and_render(template: dict, output_name: str, *, variables: dict[str, str], debug: bool = False) -> str:
    target = LabelTarget(width_mm=LABEL_WIDTH_MM, height_mm=LABEL_HEIGHT_MM, dpi=LABEL_DPI)
    zpl = compile_zpl(template, target=target, variables=variables, debug=debug)
    output_path = Path(__file__).resolve().parents[1] / "artifacts" / f"{output_name}.png"
    _render_png(zpl, output_path, target=target)
    return zpl


def _base_template(name: str, element: dict) -> dict:
    return {
        "schema_version": 1,
        "name": name,
        "defaults": {
            "leaf_padding_mm": [1.0, 1.0, 1.0, 1.0],
            "render": {"missing_variables": "error", "emit_ci28": False},
        },
        "layout": {"kind": "leaf", "elements": [element]},
    }


def _text_element(**overrides: object) -> dict:
    element = {"type": "text", "text": "Asset {name}"}
    element.update(overrides)
    return element


def _qr_element(**overrides: object) -> dict:
    element = {"type": "qr", "data": "{code}"}
    element.update(overrides)
    return element


def _dm_element(**overrides: object) -> dict:
    element = {"type": "datamatrix", "data": "{payload}", "module_size_mm": 0.6}
    element.update(overrides)
    return element


def _line_element(**overrides: object) -> dict:
    element = {"type": "line", "orientation": "h", "thickness_mm": 0.6}
    element.update(overrides)
    return element


TEXT_CASES = [
    ("text_id", _text_element(id="text-id")),
    ("text_font_height_mm", _text_element(font_height_mm=6.0)),
    ("text_font_width_mm", _text_element(font_height_mm=4.0, font_width_mm=2.5)),
    ("text_wrap_word", _text_element(wrap="word", text="Long text {name} " * 6)),
    ("text_wrap_char", _text_element(wrap="char", text="LongTextName" * 8)),
    ("text_fit_overflow", _text_element(fit="overflow", wrap="none", text="Overflow " * 10)),
    ("text_fit_wrap", _text_element(fit="wrap", wrap="word", text="Wrap text " * 8)),
    ("text_fit_shrink", _text_element(fit="shrink_to_fit", wrap="word", text="Shrink text " * 8)),
    ("text_fit_truncate", _text_element(fit="truncate", wrap="word", max_lines=1, text="Truncate me " * 6)),
    ("text_max_lines", _text_element(wrap="word", max_lines=2, text="Line one " * 6)),
    ("text_align_h_center", _text_element(align_h="center")),
    ("text_align_v_bottom", _text_element(align_v="bottom", text="Line 1\\nLine 2")),
    ("text_padding_mm", _text_element(padding_mm=[2.0, 3.0, 2.0, 3.0])),
    ("text_min_size_mm", _text_element(min_size_mm=[20.0, 8.0])),
    ("text_max_size_mm", _text_element(max_size_mm=[40.0, 12.0])),
]


@pytest.mark.parametrize(("name", "element"), TEXT_CASES)
def test_labelary_text_property(name: str, element: dict) -> None:
    template = _base_template(name, element)
    zpl = _compile_and_render(template, name, variables=DEFAULT_VARS, debug=False)
    assert "^XA" in zpl


QR_CASES = [
    ("qr_id", _qr_element(id="qr-id")),
    ("qr_magnification", _qr_element(magnification=3)),
    ("qr_error_correction", _qr_element(error_correction="Q")),
    ("qr_input_mode_a", _qr_element(input_mode="A")),
    ("qr_input_mode_m", _qr_element(input_mode="M", character_mode="A")),
    ("qr_quiet_zone_mm", _qr_element(quiet_zone_mm=1.2)),
    ("qr_padding_mm", _qr_element(padding_mm=[1.5, 1.0, 1.5, 1.0])),
    ("qr_min_size_mm", _qr_element(min_size_mm=[15.0, 15.0])),
    ("qr_max_size_mm", _qr_element(max_size_mm=[40.0, 40.0])),
]


@pytest.mark.parametrize(("name", "element"), QR_CASES)
def test_labelary_qr_property(name: str, element: dict) -> None:
    template = _base_template(name, element)
    zpl = _compile_and_render(template, name, variables=DEFAULT_VARS, debug=False)
    assert "^BQN" in zpl


DM_CASES = [
    ("dm_id", _dm_element(id="dm-id")),
    ("dm_module_size_mm", _dm_element(module_size_mm=0.8)),
    ("dm_quality", _dm_element(quality=200)),
    ("dm_columns", _dm_element(columns=12)),
    ("dm_rows", _dm_element(rows=12)),
    ("dm_format_id", _dm_element(format_id=6)),
    ("dm_escape_char", _dm_element(escape_char="!")),
    ("dm_quiet_zone_mm", _dm_element(quiet_zone_mm=1.0)),
    ("dm_padding_mm", _dm_element(padding_mm=[1.0, 2.0, 1.0, 2.0])),
    ("dm_min_size_mm", _dm_element(min_size_mm=[12.0, 12.0])),
    ("dm_max_size_mm", _dm_element(max_size_mm=[40.0, 40.0])),
]


@pytest.mark.parametrize(("name", "element"), DM_CASES)
def test_labelary_datamatrix_property(name: str, element: dict) -> None:
    template = _base_template(name, element)
    zpl = _compile_and_render(template, name, variables=DEFAULT_VARS, debug=False)
    assert "^BXN" in zpl


LINE_CASES = [
    ("line_id", _line_element(id="line-id")),
    ("line_orientation_h", _line_element(orientation="h", align="center")),
    ("line_orientation_v", _line_element(orientation="v", align="center")),
    ("line_thickness_mm", _line_element(thickness_mm=1.2)),
    ("line_align_end", _line_element(align="end")),
    ("line_padding_mm", _line_element(padding_mm=[1.0, 2.0, 1.0, 2.0])),
]


@pytest.mark.parametrize(("name", "element"), LINE_CASES)
def test_labelary_line_property(name: str, element: dict) -> None:
    template = _base_template(name, element)
    zpl = _compile_and_render(template, name, variables=DEFAULT_VARS, debug=False)
    assert "^GB" in zpl


def test_labelary_grid_layout_with_dividers() -> None:
    template = {
        "schema_version": 1,
        "name": "grid_layout_dividers",
        "defaults": {"leaf_padding_mm": [1.0, 1.0, 1.0, 1.0]},
        "layout": {
            "kind": "split",
            "direction": "v",
            "ratio": 0.6,
            "gutter_mm": 1.2,
            "divider": {"visible": True, "thickness_mm": 0.4},
            "children": [
                {
                    "kind": "split",
                    "direction": "h",
                    "ratio": 0.5,
                    "gutter_mm": 1.0,
                    "divider": {"visible": True, "thickness_mm": 0.3},
                    "children": [
                        {"kind": "leaf", "elements": [_text_element(text="Top Left")]},
                        {"kind": "leaf", "elements": [_text_element(text="Bottom Left")]},
                    ],
                },
                {"kind": "leaf", "elements": [_text_element(text="Right")]},
            ],
        },
    }
    zpl = _compile_and_render(template, "grid_layout_dividers", variables=DEFAULT_VARS, debug=True)
    assert zpl.count("^GB") >= 2


def test_labelary_split_overflow_multiline() -> None:
    template = {
        "schema_version": 1,
        "name": "split_overflow_multiline",
        "defaults": {"leaf_padding_mm": [1.0, 1.0, 1.0, 1.0]},
        "layout": {
            "kind": "split",
            "direction": "v",
            "ratio": 0.45,
            "gutter_mm": 1.0,
            "children": [
                {
                    "kind": "leaf",
                    "elements": [
                        _text_element(
                            text="Overflow {name} " * 12,
                            wrap="word",
                            fit="overflow",
                            max_lines=3,
                            align_h="left",
                            align_v="top",
                        )
                    ],
                },
                {
                    "kind": "leaf",
                    "elements": [_text_element(text="Right pane")],
                },
            ],
        },
    }
    zpl = _compile_and_render(template, "split_overflow_multiline", variables=DEFAULT_VARS, debug=True)
    assert "^FB" in zpl


WRAP_SPLIT_CASES = [
    ("wrap_none", "none"),
    ("wrap_word", "word"),
    ("wrap_char", "char"),
]


@pytest.mark.parametrize(("case_name", "wrap_mode"), WRAP_SPLIT_CASES)
def test_labelary_split_wrap_modes(case_name: str, wrap_mode: str) -> None:
    long_text = "This is a long line of text meant to overflow the left pane. " * 6
    template = {
        "schema_version": 1,
        "name": f"split_wrap_{case_name}",
        "defaults": {"leaf_padding_mm": [1.0, 1.0, 1.0, 1.0]},
        "layout": {
            "kind": "split",
            "direction": "v",
            "ratio": 0.5,
            "gutter_mm": 1.0,
            "divider": {"visible": True, "thickness_mm": 0.4},
            "children": [
                {
                    "kind": "leaf",
                    "elements": [
                        _text_element(
                            text=long_text,
                            wrap=wrap_mode,
                            fit="wrap" if wrap_mode != "none" else "overflow",
                            max_lines=3,
                            align_h="left",
                            align_v="top",
                        )
                    ],
                },
                {
                    "kind": "leaf",
                    "elements": [_text_element(text="Right pane")],
                },
            ],
        },
    }
    zpl = _compile_and_render(template, f"split_wrap_{case_name}", variables=DEFAULT_VARS, debug=True)
    assert "^GB" in zpl
