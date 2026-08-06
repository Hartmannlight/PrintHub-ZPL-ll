from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen


JsonReader = Callable[[str, float], Mapping[str, Any]]


def _read_json(url: str, timeout_s: float) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - URL comes from trusted printer config
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Dynamic media response must be a JSON object")
    return payload


def resolve_dynamic_printer_media(
    printer: Mapping[str, Any],
    *,
    read_json: JsonReader = _read_json,
) -> dict[str, Any]:
    """Return a printer copy hydrated with live media, falling back to configured values."""

    resolved = deepcopy(dict(printer))
    media = resolved.get("media")
    if not isinstance(media, dict):
        return resolved
    source = media.get("dynamic_source")
    if not isinstance(source, Mapping) or source.get("kind") != "zpl_emulator_settings":
        return resolved

    try:
        url = str(source["url"])
        timeout_s = float(source.get("timeout_ms", 1000)) / 1000
        payload = read_json(url, timeout_s)
        width_mm = float(payload["label_width_mm"])
        height_mm = float(payload["label_height_mm"])
        dpmm = float(payload["dpmm"])
        if not all(math.isfinite(value) and value > 0 for value in (width_mm, height_mm, dpmm)):
            raise ValueError("Dynamic media dimensions and dpmm must be positive finite numbers")
    except (KeyError, TypeError, ValueError, OSError):
        return resolved

    loaded = media.get("loaded")
    if not isinstance(loaded, dict):
        loaded = {}
        media["loaded"] = loaded
    loaded["width_mm"] = width_mm
    loaded["height_mm"] = height_mm

    alignment = resolved.get("alignment")
    if not isinstance(alignment, dict):
        alignment = {}
        resolved["alignment"] = alignment
    alignment["dpi"] = round(dpmm * 25.4)
    return resolved
