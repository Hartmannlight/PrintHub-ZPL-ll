from __future__ import annotations

from zplgrid.labelary import _parse_labelary_warnings


def test_parse_labelary_warnings() -> None:
    header = "303|1|^GB|2|Value 1 is less than minimum value 3; used 3 instead|591|3|||Ignored unrecognized content"
    warnings = _parse_labelary_warnings(header)

    assert len(warnings) == 2
    assert warnings[0].byte_index == 303
    assert warnings[0].byte_size == 1
    assert warnings[0].command == "^GB"
    assert warnings[0].param_index == 2
    assert "minimum value" in warnings[0].message

    assert warnings[1].byte_index == 591
    assert warnings[1].byte_size == 3
    assert warnings[1].command == ""
    assert warnings[1].param_index is None
    assert warnings[1].message == "Ignored unrecognized content"
