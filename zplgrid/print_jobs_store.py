from __future__ import annotations

import json
import hashlib
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_jobs_lock = threading.Lock()


class IdempotencyConflict(ValueError):
    pass


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


def _document_path(job_id: str) -> Path:
    normalized = _job_path(job_id).stem
    return jobs_dir() / "documents" / f"{normalized}.json"


def _artifacts_path(job_id: str) -> Path:
    normalized = _job_path(job_id).stem
    return jobs_dir() / "artifacts" / f"{normalized}.json"


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


def _request_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _existing_idempotent_job(key: str | None, fingerprint: str) -> dict[str, Any] | None:
    if not key:
        return None
    existing = find_by_idempotency_key(key)
    if existing is None:
        return None
    previous = existing.get("request_fingerprint")
    if previous is not None and previous != fingerprint:
        raise IdempotencyConflict(
            "The idempotency key was already used for different print content"
        )
    return existing


def create_job(
    *,
    printer_id: str,
    template_id: str | None,
    template: dict[str, Any] | None = None,
    variables: dict[str, Any],
    target: dict[str, Any] | None,
    idempotency_key: str | None,
    origin: str | None,
    origin_reference: str | None = None,
    output_mode: str = "auto",
) -> dict[str, Any]:
    request_fingerprint = _request_fingerprint(
        {
            "kind": "template",
            "printer_id": printer_id,
            "template_id": template_id,
            "template": template,
            "variables": variables,
            "target": target,
            "output_mode": output_mode,
            "origin": origin,
            "origin_reference": origin_reference,
        }
    )
    with _jobs_lock:
        existing = _existing_idempotent_job(idempotency_key, request_fingerprint)
        if existing is not None:
            return existing
        now = _now()
        payload: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "source_kind": "inline_template" if template is not None else "template",
            "status": "queued",
            "printer_id": printer_id,
            "template_id": template_id,
            "template": template,
            "variables": variables,
            "target": target,
            "output_mode": output_mode,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
            "origin": origin,
            "origin_reference": origin_reference,
            "attempts": 0,
            "bytes_sent": None,
            "downstream_job_id": None,
            "downstream_job_state": None,
            "downstream_jobs": [],
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        _write_atomic(_job_path(payload["id"]), payload)
        return payload


def create_raster_job(
    *,
    printer_id: str,
    document: dict[str, Any],
    ticket: dict[str, Any],
    idempotency_key: str | None,
    origin: str | None,
    origin_reference: str | None = None,
) -> dict[str, Any]:
    request_fingerprint = _request_fingerprint(
        {
            "kind": "raster_or_document",
            "printer_id": printer_id,
            "document": document,
            "ticket": ticket,
            "origin": origin,
            "origin_reference": origin_reference,
        }
    )
    with _jobs_lock:
        existing = _existing_idempotent_job(idempotency_key, request_fingerprint)
        if existing is not None:
            return existing
        now = _now()
        job_id = str(uuid.uuid4())
        source_kind = "document" if document.get("kind") == "source_document" else "raster"
        pages = document.get("pages")
        payload: dict[str, Any] = {
            "id": job_id,
            "source_kind": source_kind,
            "status": "queued",
            "printer_id": printer_id,
            "template_id": None,
            "page_count": len(pages) if isinstance(pages, list) else None,
            "ticket": ticket,
            "idempotency_key": idempotency_key,
            "request_fingerprint": request_fingerprint,
            "origin": origin,
            "origin_reference": origin_reference,
            "attempts": 0,
            "bytes_sent": None,
            "downstream_job_id": None,
            "downstream_job_state": None,
            "downstream_jobs": [],
            "preview_png_base64": None,
            "warning": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        _write_atomic(_document_path(job_id), document)
        _write_atomic(_job_path(job_id), payload)
        return payload


def create_artifact_reprint(
    original: dict[str, Any], *, idempotency_key: str | None
) -> dict[str, Any]:
    original_id = str(original["id"])
    artifacts = load_job_artifacts(original_id)
    if artifacts is None:
        raise ValueError("The original job has no immutable artifacts to reprint")
    fingerprint = _request_fingerprint(
        {"kind": "artifact_reprint", "original_id": original_id, "artifacts": artifacts}
    )
    with _jobs_lock:
        existing = _existing_idempotent_job(idempotency_key, fingerprint)
        if existing is not None:
            return existing
        now = _now()
        job_id = str(uuid.uuid4())
        payload = {
            "id": job_id,
            "source_kind": "artifact_reprint",
            "status": "queued",
            "printer_id": original["printer_id"],
            "template_id": original.get("template_id"),
            "page_count": original.get("page_count"),
            "reprint_of": original_id,
            "idempotency_key": idempotency_key,
            "request_fingerprint": fingerprint,
            "origin": "explicit_reprint",
            "origin_reference": original_id,
            "attempts": 0,
            "bytes_sent": None,
            "downstream_job_id": None,
            "downstream_job_state": None,
            "downstream_jobs": [],
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        save_job_artifacts(job_id, artifacts)
        _write_atomic(_job_path(job_id), payload)
        return payload


def load_job_document(job_id: str) -> dict[str, Any]:
    path = _document_path(job_id)
    if not path.exists():
        raise FileNotFoundError(job_id)
    return json.loads(path.read_text(encoding="utf-8"))


def save_job_artifacts(job_id: str, artifact_set: dict[str, Any]) -> None:
    """Persist immutable, fully evaluated bytes before any service request."""
    path = _artifacts_path(job_id)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != artifact_set:
            raise ValueError("Immutable print artifacts already exist with different content")
        return
    _write_atomic(path, artifact_set)


def load_job_artifacts(job_id: str) -> dict[str, Any] | None:
    path = _artifacts_path(job_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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


def claim_job(job_id: str) -> dict[str, Any] | None:
    """Atomically claim one safely undispatched job for the single delivery attempt."""
    with _jobs_lock:
        payload = load_job(job_id)
        if payload.get("status") not in {"queued", "waiting_for_service"}:
            return None
        payload["attempts"] = int(payload.get("attempts") or 0) + 1
        payload["status"] = "processing"
        payload["error"] = None
        payload["updated_at"] = _now()
        _write_atomic(_job_path(job_id), payload)
        return payload


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return list_all_jobs()[: max(1, min(limit, 1000))]


def list_all_jobs() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in jobs_dir().glob("*.json"):
        try:
            result.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    result.sort(key=lambda entry: str(entry.get("created_at") or ""), reverse=True)
    return result


def recover_interrupted_jobs() -> int:
    """Mark jobs interrupted mid-dispatch as unknown instead of retrying them automatically."""
    recovered = 0
    for payload in list_all_jobs():
        if payload.get("status") != "processing":
            continue
        payload["status"] = "outcome_unknown"
        payload["error"] = "PrintHub stopped while dispatching this job; verify the printer before retrying."
        save_job(payload)
        recovered += 1
    return recovered
