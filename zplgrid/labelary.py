from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
import time

import requests


_RATE_LIMIT_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0
_MIN_SECONDS_BETWEEN_REQUESTS = 0.4


@dataclass(frozen=True)
class LabelaryWarning:
    byte_index: int
    byte_size: int
    command: str
    param_index: int | None
    message: str


def _compact_zpl(zpl: str) -> str:
    return "".join(line.strip() for line in zpl.splitlines() if line.strip())


def _rate_limit_labelary() -> None:
    global _LAST_REQUEST_AT
    with _RATE_LIMIT_LOCK:
        now = time.monotonic()
        elapsed = now - _LAST_REQUEST_AT
        if elapsed < _MIN_SECONDS_BETWEEN_REQUESTS:
            time.sleep(_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
        _LAST_REQUEST_AT = time.monotonic()


def _parse_labelary_warnings(header: str) -> list[LabelaryWarning]:
    if not header:
        return []
    parts = header.split('|')
    warnings: list[LabelaryWarning] = []
    for i in range(0, len(parts), 5):
        if i + 4 >= len(parts):
            break
        byte_index_raw, byte_size_raw, command, param_raw, message = parts[i:i + 5]
        try:
            byte_index = int(byte_index_raw)
        except ValueError:
            byte_index = 0
        try:
            byte_size = int(byte_size_raw)
        except ValueError:
            byte_size = 0
        param_index = int(param_raw) if param_raw else None
        warnings.append(
            LabelaryWarning(
                byte_index=byte_index,
                byte_size=byte_size,
                command=command,
                param_index=param_index,
                message=message,
            )
        )
    return warnings


def render_labelary_png(
    zpl: str,
    out_path: Path,
    dpmm: int = 8,
    label_width_in: float = 4.0,
    label_height_in: float = 6.0,
    index: int = 0,
    timeout_s: int = 30,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    url = f'http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{label_width_in}x{label_height_in}/{index}/'
    files = {'file': zpl}
    headers = {'Accept': 'image/png'}

    for attempt in range(3):
        _rate_limit_labelary()
        resp = requests.post(url, headers=headers, files=files, stream=True, timeout=timeout_s)
        if resp.status_code == 429 and attempt < 2:
            time.sleep(0.75)
            continue
        if resp.status_code != 200:
            raise RuntimeError(f'Labelary error {resp.status_code}: {resp.text}')
        break

    with out_path.open('wb') as f:
        for chunk in resp.iter_content(chunk_size=1024 * 64):
            if chunk:
                f.write(chunk)

    return out_path


def render_labelary_png_bytes(
    zpl: str,
    *,
    dpmm: int = 8,
    label_width_in: float = 4.0,
    label_height_in: float = 6.0,
    index: int = 0,
    timeout_s: int = 30,
) -> bytes:
    url = f'http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{label_width_in}x{label_height_in}/{index}/'
    files = {'file': zpl}
    headers = {'Accept': 'image/png'}

    for attempt in range(3):
        _rate_limit_labelary()
        resp = requests.post(url, headers=headers, files=files, stream=True, timeout=timeout_s)
        if resp.status_code == 429 and attempt < 2:
            time.sleep(0.75)
            continue
        if resp.status_code != 200:
            raise RuntimeError(f'Labelary error {resp.status_code}: {resp.text}')
        break

    return resp.content


def lint_labelary_zpl(
    zpl: str,
    *,
    dpmm: int = 8,
    label_width_in: float = 4.0,
    label_height_in: float = 6.0,
    index: int = 0,
    timeout_s: int = 30,
    compact: bool = True,
) -> list[LabelaryWarning]:
    if compact:
        zpl = _compact_zpl(zpl)
    url = f'http://api.labelary.com/v1/printers/{dpmm}dpmm/labels/{label_width_in}x{label_height_in}/{index}/'
    headers = {'Accept': 'image/png', 'X-Linter': 'On', 'Content-Type': 'application/x-www-form-urlencoded'}

    for attempt in range(3):
        _rate_limit_labelary()
        resp = requests.post(url, headers=headers, data=zpl.encode('utf-8'), stream=True, timeout=timeout_s)
        if resp.status_code == 429 and attempt < 2:
            time.sleep(0.75)
            continue
        if resp.status_code != 200:
            raise RuntimeError(f'Labelary error {resp.status_code}: {resp.text}')
        break

    return _parse_labelary_warnings(resp.headers.get('X-Warnings', ''))
