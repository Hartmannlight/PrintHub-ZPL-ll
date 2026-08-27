from __future__ import annotations

import pytest

from zplgrid.exceptions import TemplateValidationError
from zplgrid.parser import load_template


def _template(element: dict) -> dict:
    return {
        "schema_version": 1,
        "layout": {"kind": "leaf", "elements": [element]},
    }


@pytest.mark.parametrize(
    "element",
    [
        {"type": "text", "text": "defaults are valid"},
        {"type": "text", "text": "inferred fit", "wrap": "word"},
        {"type": "text", "text": "overflow", "fit": "overflow", "wrap": "none"},
        {"type": "text", "text": "wrap", "fit": "wrap", "wrap": "word"},
        {"type": "text", "text": "wrap", "fit": "wrap", "wrap": "char"},
        {"type": "text", "text": "truncate", "fit": "truncate", "wrap": "word"},
        {"type": "text", "text": "truncate", "fit": "truncate", "wrap": "char"},
        {"type": "text", "text": "shrink", "fit": "shrink_to_fit", "wrap": "word"},
        {"type": "text", "text": "shrink", "fit": "shrink_to_fit", "wrap": "char"},
    ],
)
def test_valid_text_fit_wrap_combinations_are_accepted(element: dict) -> None:
    load_template(_template(element))


@pytest.mark.parametrize(
    "element",
    [
        {"type": "text", "text": "bad", "fit": "overflow", "wrap": "word"},
        {"type": "text", "text": "bad", "fit": "overflow", "wrap": "char"},
        {"type": "text", "text": "bad", "fit": "wrap", "wrap": "none"},
        {"type": "text", "text": "bad", "fit": "truncate", "wrap": "none"},
        {"type": "text", "text": "bad", "fit": "shrink_to_fit", "wrap": "none"},
        {"type": "text", "text": "bad", "fit": "unknown", "wrap": "word"},
        {"type": "text", "text": "bad", "max_lines": 0},
        {"type": "text", "text": "bad", "max_lines": -1},
    ],
)
def test_invalid_text_settings_are_rejected(element: dict) -> None:
    with pytest.raises(TemplateValidationError):
        load_template(_template(element))
