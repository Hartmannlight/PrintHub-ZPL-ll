from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone
import uuid

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field


RASTER_MIME = "application/vnd.printhub.raster-page+json"
DATA = Path(os.getenv("RASTER_TEST_DATA_DIR", "/data"))
def _configured_token() -> str:
    inline = os.getenv("RASTER_TEST_TOKEN", "").strip()
    path = os.getenv("RASTER_TEST_TOKEN_FILE", "").strip()
    if inline and path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8").strip() if path else inline
    except OSError:
        return ""


TOKEN = _configured_token()
SERVICE_ID = os.getenv("RASTER_TEST_SERVICE_ID", "raster-test-service")
PRINTER_ID = os.getenv("RASTER_TEST_PRINTER_ID", "raster-simulator")
DPI = int(os.getenv("RASTER_TEST_DPI", "203"))
WIDTH = int(os.getenv("RASTER_TEST_WIDTH_PX", "400"))
HEIGHT = int(os.getenv("RASTER_TEST_HEIGHT_PX", "200"))
_lock = threading.RLock()

app = FastAPI(title="PrintHub raster test service", version="0.1.0")


class ProtocolError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message


@app.exception_handler(ProtocolError)
def protocol_error(_request, error: ProtocolError):
    return JSONResponse(
        status_code=error.status,
        content={
            "error": {"code": error.code, "message": error.message, "details": {}}
        },
    )


class Artifact(BaseModel):
    mime_type: str
    sha256: str = Field(pattern="^[a-fA-F0-9]{64}$")
    data_base64: str


class SubmitJob(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    media_revision: str | None = None
    copies: int = Field(default=1, ge=1, le=999)
    reprint_of: str | None = None
    artifacts: list[Artifact] = Field(min_length=1, max_length=100)
    options: dict = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _authorize(authorization: str | None) -> None:
    if len(TOKEN) < 24:
        raise ProtocolError(503, "not_configured", "Raster test token is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not secrets.compare_digest(TOKEN, supplied):
        raise ProtocolError(401, "unauthorized", "A valid raster test token is required")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _jobs() -> Path:
    return DATA / "jobs"


def _load_job(job_id: str) -> dict:
    path = _jobs() / f"{uuid.UUID(job_id)}.json"
    if not path.exists():
        raise ProtocolError(404, "not_found", "Job not found")
    return json.loads(path.read_text(encoding="utf-8"))


def _error(status: int, code: str, message: str):
    raise ProtocolError(status, code, message)


def _mode() -> str:
    return os.getenv("RASTER_TEST_MODE", "normal").strip().lower()


def _require_online() -> None:
    if _mode() == "offline":
        _error(503, "simulated_offline", "The raster service is intentionally offline")


@app.get("/healthz")
def healthz():
    _require_online()
    return {"status": "ok", "simulation": True}


@app.get("/v2/service")
def service(authorization: str | None = Header(default=None)):
    _require_online()
    _authorize(authorization)
    return {
        "protocol": {"name": "printhub-print-service", "major": 2, "minor": 0},
        "service_id": SERVICE_ID,
        "service_type": "raster_test_service",
        "display_name": "Raster test service (simulation)",
        "version": "0.1.0",
        "capabilities": ["catalog", "jobs", "idempotency_lookup", "simulated_confirmation"],
    }


def _printer():
    return {
        "id": PRINTER_ID,
        "service_id": SERVICE_ID,
        "display_name": "Raster simulator",
        "device_family": "simulated_raster",
        "enabled": True,
        "accepted_mime_types": [RASTER_MIME],
        "capabilities": {
            "status_probe": False,
            "media": True,
            "device_configuration": False,
            "queue_control": False,
            "simulated": True,
        },
        "profile": {
            "resolution_dpi": DPI,
            "max_width_dots": WIDTH,
            "max_length_dots": HEIGHT,
        },
        "status": {"ready": {"state": "value", "value": True, "source": "simulation"}},
        "observed_at": _now(),
        "media": {
            "revision": "simulated-media-v1",
            "state": {
                "remaining_labels": 1000000,
                "media": {
                    "display_name": "Simulated white labels",
                    "width_mm": WIDTH / DPI * 25.4,
                    "height_mm": HEIGHT / DPI * 25.4,
                    "color": {"name": "white", "hex": "#ffffff"},
                },
            },
        },
    }


@app.get("/v2/printers")
def printers(authorization: str | None = Header(default=None)):
    _require_online()
    _authorize(authorization)
    return {"items": [_printer()]}


@app.get("/v2/printers/{printer_id}")
def printer(printer_id: str, authorization: str | None = Header(default=None)):
    _require_online()
    _authorize(authorization)
    if printer_id != PRINTER_ID:
        _error(404, "not_found", "Printer not found")
    return _printer()


def _decode_page(artifact: Artifact) -> tuple[dict, bytes]:
    if artifact.mime_type != RASTER_MIME:
        _error(400, "unsupported_mime_type", "This simulation accepts only PrintHub raster pages")
    try:
        source = base64.b64decode(artifact.data_base64, validate=True)
    except ValueError:
        _error(400, "invalid_base64", "Artifact is not valid base64")
    if hashlib.sha256(source).hexdigest().lower() != artifact.sha256.lower():
        _error(400, "checksum_mismatch", "Artifact checksum does not match")
    try:
        page = json.loads(source)
        width = int(page["width_px"])
        height = int(page["height_px"])
        dpi = int(page["dpi"])
        copies = int(page["copies"])
        packed = base64.b64decode(page["black_bits_base64"], validate=True)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        _error(400, "invalid_raster", "Raster page is invalid")
    expected = ((width + 7) // 8) * height
    if page.get("version") != 1 or copies != 1 or len(packed) != expected:
        _error(400, "invalid_raster", "Raster version, copies, or byte length is invalid")
    if width <= 0 or height <= 0 or width > WIDTH or height > HEIGHT or dpi != DPI:
        _error(400, "profile_mismatch", "Raster does not match the simulated printer profile")
    if width % 8:
        mask = (1 << (8 - width % 8)) - 1
        row_bytes = (width + 7) // 8
        if any(packed[row * row_bytes + row_bytes - 1] & mask for row in range(height)):
            _error(400, "invalid_padding", "Unused raster row bits must be white")
    return page, packed


def _save_png(path: Path, page: dict, packed: bytes) -> None:
    width, height = int(page["width_px"]), int(page["height_px"])
    row_bytes = (width + 7) // 8
    image = Image.new("1", (width, height), 1)
    pixels = image.load()
    for y in range(height):
        for x in range(width):
            black = packed[y * row_bytes + x // 8] & (0x80 >> (x % 8))
            pixels[x, y] = 0 if black else 1
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")


@app.post("/v2/printers/{printer_id}/jobs", status_code=202)
def submit_job(
    printer_id: str,
    request: SubmitJob,
    authorization: str | None = Header(default=None),
):
    _require_online()
    _authorize(authorization)
    if printer_id != PRINTER_ID:
        _error(404, "not_found", "Printer not found")
    canonical = {
        "printer_id": printer_id,
        "copies": request.copies,
        "media_revision": request.media_revision,
        "reprint_of": request.reprint_of,
        "options": request.options,
        "artifacts": [
            {"mime_type": item.mime_type, "sha256": item.sha256.lower()}
            for item in request.artifacts
        ],
    }
    request_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with _lock:
        for path in _jobs().glob("*.json") if _jobs().exists() else ():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing["idempotency_key"] == request.idempotency_key:
                if existing["request_sha256"] != request_hash:
                    _error(409, "idempotency_conflict", "Idempotency key identifies another job")
                return existing
        decoded = [_decode_page(artifact) for artifact in request.artifacts]
        job_id = str(uuid.uuid4())
        created = _now()
        mode = _mode()
        if mode == "slow":
            time.sleep(max(0, int(os.getenv("RASTER_TEST_DELAY_MS", "1000"))) / 1000)
        job = {
            "id": job_id,
            "printer_id": printer_id,
            "state": "outcome_unknown" if mode == "outcome_unknown" else "completed_observed",
            "created_at": created,
            "updated_at": created,
            "label_count": len(decoded) * request.copies,
            "idempotency_key": request.idempotency_key,
            "request_sha256": request_hash,
            "device_payload_bytes": sum(len(value) for _, value in decoded),
            "bytes_transferred": sum(len(value) for _, value in decoded),
            "delivery_attempts": 1,
            "error": "Simulated ambiguous physical outcome" if mode == "outcome_unknown" else None,
            "simulation": True,
        }
        _atomic_json(_jobs() / f"{job_id}.json", job)
        for copy in range(1, request.copies + 1):
            for number, (page, packed) in enumerate(decoded, start=1):
                _save_png(DATA / "output" / job_id / f"copy-{copy}-page-{number}.png", page, packed)
        if mode == "lost_response_once":
            marker = DATA / "lost-response-markers" / request_hash
            if not marker.exists():
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(job_id, encoding="utf-8")
                _error(503, "simulated_lost_response", "Job was accepted but its response was lost")
        return job


@app.get("/v2/jobs/by-idempotency/{key}")
def job_by_key(key: str, authorization: str | None = Header(default=None)):
    _require_online()
    _authorize(authorization)
    with _lock:
        for path in _jobs().glob("*.json") if _jobs().exists() else ():
            job = json.loads(path.read_text(encoding="utf-8"))
            if job["idempotency_key"] == key:
                return job
    _error(404, "not_found", "Job not found")


@app.get("/v2/jobs/{job_id}")
def job(job_id: str, authorization: str | None = Header(default=None)):
    _require_online()
    _authorize(authorization)
    return _load_job(job_id)


@app.get("/v2/jobs")
def jobs(authorization: str | None = Header(default=None)):
    _require_online()
    _authorize(authorization)
    items = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(_jobs().glob("*.json"))
    ] if _jobs().exists() else []
    return {"items": items, "next_cursor": len(items)}
