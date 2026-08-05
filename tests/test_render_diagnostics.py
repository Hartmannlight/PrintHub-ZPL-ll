from __future__ import annotations

import base64
import json

from zplgrid import api


def _request() -> api.RenderRequest:
    return api.RenderRequest(
        template={
            "schema_version": 1,
            "name": "diagnostics",
            "defaults": {"leaf_padding_mm": [1, 1, 1, 1]},
            "layout": {
                "kind": "leaf",
                "alias": "message",
                "elements": [{
                    "type": "text",
                    "id": "message-text",
                    "text": "Alpha bravo charlie delta echo foxtrot golf hotel india juliet",
                    "font_height_mm": 4,
                    "fit": "wrap",
                    "wrap": "word",
                    "max_lines": 1,
                    "align_h": "left",
                    "align_v": "top",
                }],
            },
        },
        target=api.RenderTarget(width_mm=40, height_mm=20, dpi=203),
    )


def test_render_zpl_returns_text_layout_diagnostics() -> None:
    response = api.render_zpl(_request())

    assert "^FB" not in response.zpl
    assert response.diagnostics[0]["code"] == "text_max_lines_exceeded"
    assert response.diagnostics[0]["element_id"] == "message-text"
    assert response.diagnostics[0]["leaf_alias"] == "message"


def test_render_png_exposes_diagnostics_header(monkeypatch) -> None:
    monkeypatch.setattr(api, "_labelary_api_enabled", lambda: True)
    monkeypatch.setattr(api, "render_labelary_png_bytes", lambda *args, **kwargs: b"png")

    response = api.render_png(_request())
    encoded = response.headers["x-printhub-diagnostics"]
    diagnostics = json.loads(base64.urlsafe_b64decode(encoded).decode("ascii"))

    assert response.body == b"png"
    assert diagnostics[0]["code"] == "text_max_lines_exceeded"

