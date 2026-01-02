import json
from pathlib import Path

from zplgrid import LabelTarget, compile_zpl


def test_compile_example_template_smoke() -> None:
    root = Path(__file__).resolve().parents[1]
    template_path = root / "examples" / "qr_left_text_right.template.json"
    template = json.loads(template_path.read_text(encoding="utf-8"))

    zpl = compile_zpl(
        template,
        target=LabelTarget(width_mm=74.0, height_mm=26.0, dpi=203),
        variables={
            "asset_id": "A-001-2025",
            "title": "Cable Box 1",
            "subtitle": "USB-C / PD 100W",
        },
        debug=False,
    )

    assert "^XA" in zpl
    assert "^XZ" in zpl
