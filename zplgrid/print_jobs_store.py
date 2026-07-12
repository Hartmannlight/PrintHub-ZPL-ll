from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_jobs_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def jobs_dir() -> Path:
    path = Path(os.getenv("ZPLGRID_PRINT_JOBS_DIR", "/data/print-jobs"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(job_id: str) -> Path:
    try:
        normalized = str(uuid.UUID(job_id))
    except ValueError as exc:
        raise ValueError("Invalid print job id") from exc
    return jobs_dir() / f"{normalized}.json"


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def find_by_idempotency_key(key: str) -> dict[str, Any] | None:
    if not key:
        return None
    for path in jobs_dir().glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if payload.get("idempotency_key") == key:
            return payload
    return None


def create_job(
    *,
    printer_id: str,
    template_id: str,
    variables: dict[str, Any],
    target: dict[str, Any] | None,
    idempotency_key: str | None,
    origin: str | None,
) -> dict[str, Any]:
    with _jobs_lock:
        if idempotency_key:
            existing = find_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing
        now = _now()
        payload: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "status": "queued",
            "printer_id": printer_id,
            "template_id": template_id,
            "variables": variables,
            "target": target,
            "idempotency_key": idempotency_key,
            "origin": origin,
            "attempts": 0,
            "bytes_sent": None,
            "downstream_job_id": None,
            "downstream_job_state": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        _write_atomic(_job_path(payload["id"]), payload)
        return payload


def load_job(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(payload: dict[str, Any]) -> dict[str, Any]:
    payload = dict(payload)
    payload["updated_at"] = _now()
    _write_atomic(_job_path(str(payload["id"])), payload)
    return payload


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in jobs_dir().glob("*.json"):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    result.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
    return result[: max(1, min(limit, 200))]


def recover_interrupted_jobs() -> int:
    """Mark jobs interrupted mid-dispatch as unknown instead of retrying them automatically."""
    recovered = 0
    for payload in list_jobs(200):
        if payload.get("status") != "processing":
            continue
        payload["status"] = "outcome_unknown"
        payload["error"] = "PrintHub stopped while dispatching this job; verify the printer before retrying."
        save_job(payload)
        recovered += 1
    return recovered
