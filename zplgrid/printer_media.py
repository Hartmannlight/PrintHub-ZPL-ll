from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

from .zebra_tamer import get_configuration


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
    if (resolved.get('connection') or {}).get('protocol') == 'zebra_tamer':
        return _resolve_zebra_tamer(resolved)
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


def _resolve_zebra_tamer(resolved: dict[str, Any]) -> dict[str, Any]:
    # Imported registry values remain archival only. Never present a second copy
    # of the loaded media as authoritative when the agent is unreachable.
    media = resolved.setdefault('media', {})
    media['loaded'] = None
    media['authority'] = {'source': 'zebra_tamer', 'state': 'unavailable'}
    resolved['zpl'] = {}
    alignment = resolved.setdefault('alignment', {})
    alignment.update(dpi=None, offset_x_mm=0, offset_y_mm=0)
    try:
        payload = get_configuration(resolved['connection'])
        state = payload['media'].get('state')
        device = payload['device']
        observation = device.get('observation') or {}
        dpi = observation.get('resolution_dpi') or (device.get('profile') or {}).get('resolution_dpi')
        if dpi is not None:
            dpi = int(dpi)
            if dpi <= 0:
                raise ValueError('Invalid ZebraTamer resolution')
        alignment['dpi'] = dpi
        media['authority']['state'] = 'loaded' if state else 'not_configured'
        resolved['zebra_tamer'] = {'webui_enabled': bool(payload.get('webui_enabled')), 'device': device}
        if not state:
            return resolved
        definition = state['media']
        width, height = float(definition['width_mm']), float(definition['height_mm'])
        if not all(math.isfinite(n) and n > 0 for n in (width, height)):
            raise ValueError('Invalid ZebraTamer media dimensions')
        color = definition['color']
        media['loaded'] = {'width_mm': width, 'height_mm': height, 'color': color['name'],
                           'color_hex': color.get('hex'), 'type': definition['print_technology']}
        media['agent_state'] = state
    except (RuntimeError, OSError, KeyError, TypeError, ValueError) as exc:
        media['loaded'] = None
        media['authority'] = {'source': 'zebra_tamer', 'state': 'unavailable', 'error': str(exc)}
    return resolved
