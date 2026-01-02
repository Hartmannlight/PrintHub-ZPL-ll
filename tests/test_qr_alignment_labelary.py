from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from zplgrid.labelary import render_labelary_png

pytestmark = pytest.mark.integration


def _bbox_nonwhite(image_path: Path) -> tuple[int, int, int, int]:
    img = Image.open(image_path).convert("RGB")
    pixels = img.load()
    min_x = min_y = max_x = max_y = None
    for y in range(img.height):
        for x in range(img.width):
            r, g, b = pixels[x, y]
            if r < 250 or g < 250 or b < 250:
                if min_x is None:
                    min_x = max_x = x
                    min_y = max_y = y
                else:
                    min_x = min(min_x, x)
                    max_x = max(max_x, x)
                    min_y = min(min_y, y)
                    max_y = max(max_y, y)
    if min_x is None:
        raise AssertionError("No ink detected in image")
    return (min_x, min_y, max_x, max_y)


def test_labelary_qr_has_fixed_top_offset() -> None:
    zpl = "^XA^PW591^LL208^FO0,0^BQN,2,2^FDMA,ABC^FS^XZ"
    out_path = Path(__file__).resolve().parents[1] / "artifacts" / "qr_top_offset.png"
    render_labelary_png(
        zpl,
        out_path=out_path,
        dpmm=8,
        label_width_in=74.0 / 25.4,
        label_height_in=26.0 / 25.4,
    )
    _, min_y, _, _ = _bbox_nonwhite(out_path)
    assert min_y == 10
