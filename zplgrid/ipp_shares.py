from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any


_lock = threading.RLock()


def _path() -> Path:
    configured = os.getenv("PRINTHUB_IPP_SHARES_PATH", "").strip()
    return Path(configured) if configured else Path("/data/ipp-shares.json")


def _load() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"version": 1, "shares": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1 or not isinstance(payload.get("shares"), dict):
        raise ValueError("Unsupported IPP share registry")
    return payload


def _save(payload: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ipp-shares.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def list_shares() -> list[dict[str, Any]]:
    with _lock:
        return list(_load()["shares"].values())


def save_share(
    queue_id: str, *, printer_id: str, display_name: str, enabled: bool = True
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", queue_id):
        raise ValueError("Queue ID may contain only letters, digits, hyphens and underscores")
    if not printer_id or len(printer_id) > 240:
        raise ValueError("Printer ID is required")
    if not display_name.strip() or len(display_name) > 200:
        raise ValueError("IPP display name is required")
    with _lock:
        payload = _load()
        existing = payload["shares"].get(queue_id)
        used_ports = {
            int(item["port"])
            for key, item in payload["shares"].items()
            if key != queue_id
        }
        port = int(existing["port"]) if existing else next(
            (candidate for candidate in range(8631, 8651) if candidate not in used_ports),
            0,
        )
        if not port:
            raise ValueError("No free IPP ports remain")
        record = {
            "queue_id": queue_id,
            "printer_id": printer_id,
            "display_name": display_name.strip(),
            "enabled": bool(enabled),
            "port": port,
            "resource": "/ipp/print",
        }
        payload["shares"][queue_id] = record
        _save(payload)
        return record


def set_share_enabled(queue_id: str, enabled: bool) -> dict[str, Any]:
    with _lock:
        payload = _load()
        try:
            record = payload["shares"][queue_id]
        except KeyError:
            raise KeyError(queue_id) from None
        record["enabled"] = bool(enabled)
        _save(payload)
        return dict(record)
