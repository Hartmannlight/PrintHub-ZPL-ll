#!/usr/bin/env python3
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SUPPORTED_CONTENT_TYPES = {
    "application/pdf",
    "application/postscript",
    "image/jpeg",
    "image/png",
    "image/pwg-raster",
    "image/urf",
}


def local_ipp_cancel_requested() -> bool:
    """Observe ippeveprinter's canceling state; it does not signal its command."""
    job_id = os.getenv("IPP_JOB_ID", "").strip()
    port = os.getenv("PRINTHUB_IPP_LOCAL_PORT", "").strip()
    if not job_id or not port:
        return False
    try:
        completed = subprocess.run(
            [
                "ipptool",
                "-c",
                "-d",
                f"job-id={job_id}",
                f"ipp://127.0.0.1:{port}/ipp/print",
                "/app/job-state.test",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    if completed.returncode != 0 or not rows:
        return False
    state = str(rows[-1].get("job-state") or "").strip().lower()
    message = str(rows[-1].get("job-state-message") or "").strip().lower()
    reasons = str(rows[-1].get("job-state-reasons") or "").strip().lower()
    return (
        state in {"canceled", "aborted"}
        or message.startswith("job canceling")
        or "processing-to-stop-point" in reasons
    )


def _api_token() -> str | None:
    direct = os.getenv("PRINTHUB_IPP_API_TOKEN", "").strip()
    token_file = os.getenv("PRINTHUB_IPP_API_TOKEN_FILE", "").strip()
    if direct and token_file:
        raise RuntimeError("Configure only one of PRINTHUB_IPP_API_TOKEN and PRINTHUB_IPP_API_TOKEN_FILE")
    if token_file:
        try:
            direct = Path(token_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read PrintHub API token file: {exc}") from exc
    return direct or None


def api_request(
    path: str, *, payload: dict[str, Any] | None = None, method: str | None = None
) -> dict[str, Any]:
    base_url = os.getenv("PRINTHUB_API_URL", "http://printhub:8000").rstrip("/")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(
        f"{base_url}{path}",
        data=body,
        headers=headers,
        method=method or ("POST" if body is not None else "GET"),
    )
    token = _api_token()
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(request, timeout=120) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read(16_384).decode("utf-8", errors="replace")
        raise RuntimeError(f"PrintHub rejected the job ({exc.code}): {detail}") from exc
    except (OSError, ValueError, URLError) as exc:
        raise RuntimeError(f"PrintHub request failed: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("PrintHub returned an invalid response")
    return result


def wait_for_job(
    result: dict[str, Any],
    *,
    on_update: Callable[[dict[str, Any]], None] | None = None,
    cancel_requested: threading.Event | None = None,
) -> dict[str, Any]:
    """Keep the IPP command alive until PrintHub reaches an honest handoff result."""
    job_id = str(result.get("id") or "").strip()
    configured_timeout = os.getenv("PRINTHUB_IPP_STATUS_WAIT_SECONDS", "").strip()
    timeout = max(0.0, float(configured_timeout)) if configured_timeout else None
    interval = max(0.05, float(os.getenv("PRINTHUB_IPP_STATUS_POLL_SECONDS", "0.5")))
    active = {"queued", "processing", "waiting_for_service"}
    if (
        not job_id
        or str(result.get("status") or "unknown") not in active
        or timeout == 0
    ):
        return result
    deadline = time.monotonic() + timeout if timeout is not None else None
    while deadline is None or time.monotonic() < deadline:
        if (
            (cancel_requested is not None and cancel_requested.is_set())
            or local_ipp_cancel_requested()
        ):
            result = api_request(
                f"/v1/print-jobs/{job_id}/cancel", method="POST"
            )
        else:
            sleep_for = interval
            if deadline is not None:
                sleep_for = min(interval, max(0.0, deadline - time.monotonic()))
            time.sleep(sleep_for)
            result = api_request(f"/v1/print-jobs/{job_id}")
        if on_update is not None:
            on_update(result)
        if str(result.get("status") or "unknown") not in active:
            return result
    raise RuntimeError(
        "PrintHub job is still active after the configured IPP wait limit; "
        "refusing to report it as completed"
    )


def detect_content_type(path: Path) -> str:
    configured = os.getenv("CONTENT_TYPE", "").split(";", 1)[0].strip().lower()
    if configured in SUPPORTED_CONTENT_TYPES:
        return configured
    start = path.read_bytes()[:16]
    signatures = (
        (b"%PDF-", "application/pdf"),
        (b"%!", "application/postscript"),
        (b"\x89PNG\r\n\x1a\n", "image/png"),
        (b"\xff\xd8", "image/jpeg"),
        (b"RaS2", "image/pwg-raster"),
        (b"RaS3", "image/pwg-raster"),
        (b"RaSt", "image/pwg-raster"),
        (b"UNIRAST", "image/urf"),
    )
    for signature, mime_type in signatures:
        if start.startswith(signature):
            return mime_type
    raise RuntimeError(f"Unsupported print document format: {configured or 'unknown'}")


def selected_scaling() -> str:
    requested = os.getenv("IPP_PRINT_SCALING", "").strip().lower()
    if requested in {"fit", "fill"}:
        return requested
    fallback = os.getenv("PRINTHUB_IPP_MISMATCH_POLICY", "hold").strip().lower()
    return fallback if fallback in {"hold", "fit", "fill"} else "hold"


def selected_content_optimize() -> str:
    value = os.getenv("IPP_PRINT_CONTENT_OPTIMIZE", "auto").strip().lower()
    if value in {"text", "graphics", "photo"}:
        return value
    quality = os.getenv("IPP_PRINT_QUALITY", "normal").strip().lower()
    if quality == "high":
        return "photo"
    if quality == "draft":
        return "text"
    return "auto"


def find_job_file(arguments: list[str]) -> Path:
    for argument in reversed(arguments[1:]):
        path = Path(argument)
        if path.is_file():
            return path
    raise RuntimeError("ippeveprinter did not provide a readable job file")


def idempotency_key(path: Path, queue_id: str) -> str:
    job_uuid = os.getenv("IPP_JOB_UUID", "").strip()
    if job_uuid:
        return f"ipp:{queue_id}:{job_uuid}"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    local_job_id = os.getenv("IPP_JOB_ID", "no-id").strip() or "no-id"
    return f"ipp:{queue_id}:{local_job_id}:{digest}"


def persist_job_mapping(queue_id: str, result: dict[str, Any], key: str) -> Path:
    """Persist the IPP-to-PrintHub identity without retaining document contents."""
    root = Path(
        os.getenv("PRINTHUB_IPP_MAPPING_DIR", "/var/spool/printhub-ipp/mappings")
    )
    safe_queue = "".join(character for character in queue_id if character.isalnum() or character in "-_")
    if not safe_queue or safe_queue != queue_id:
        raise RuntimeError("IPP queue ID contains unsafe characters")
    directory = root / safe_queue
    directory.mkdir(parents=True, exist_ok=True)
    identity = os.getenv("IPP_JOB_UUID", "").strip() or os.getenv("IPP_JOB_ID", "").strip() or key
    filename = hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json"
    record = {
        "schema_version": 1,
        "queue_id": queue_id,
        "ipp_job_id": os.getenv("IPP_JOB_ID", "").strip() or None,
        "ipp_job_uuid": os.getenv("IPP_JOB_UUID", "").strip() or None,
        "idempotency_key": key,
        "printhub_job_id": result.get("id"),
        "printhub_status": result.get("status"),
        "downstream_job_id": result.get("downstream_job_id"),
        "updated_at": result.get("updated_at"),
    }
    fd, temporary = tempfile.mkstemp(prefix=f".{filename}.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / filename)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return directory / filename


def main(arguments: list[str]) -> None:
    path = find_job_file(arguments)
    document = path.read_bytes()
    maximum_bytes = max(
        1, int(os.getenv("PRINTHUB_IPP_MAX_DOCUMENT_BYTES", str(32 * 1024 * 1024)))
    )
    if not document or len(document) > maximum_bytes:
        raise RuntimeError(f"IPP document must contain between 1 and {maximum_bytes} bytes")
    printer_id = os.getenv("PRINTHUB_IPP_PRINTER_ID", "virtual-zebra")
    queue_id = os.getenv("PRINTHUB_IPP_QUEUE_ID", printer_id)
    copies = max(1, min(999, int(os.getenv("IPP_COPIES", "1"))))
    key = idempotency_key(path, queue_id)
    cancel_requested = threading.Event()
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda _signum, _frame: cancel_requested.set())
    try:
        result = api_request(
            "/v1/print-jobs/documents",
            payload={
                "printer_id": printer_id,
                "mime_type": detect_content_type(path),
                "data_base64": base64.b64encode(document).decode("ascii"),
                "copies": copies,
                "scaling": selected_scaling(),
                "content_optimize": selected_content_optimize(),
                "dither": "auto",
                "idempotency_key": key,
                "origin": "ipp",
            },
        )
        persist_job_mapping(queue_id, result, key)
        result = wait_for_job(
            result,
            on_update=lambda update: persist_job_mapping(queue_id, update, key),
            cancel_requested=cancel_requested,
        )
    finally:
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
    persist_job_mapping(queue_id, result, key)
    status = str(result.get("status") or "unknown")
    if status in {"failed", "cancelled", "unconfirmed"}:
        raise RuntimeError(str(result.get("error") or "PrintHub failed the print job"))
    pages = int(result.get("page_count") or 0)
    print(f"INFO: PrintHub job {result.get('id')} is {status}", file=sys.stderr)
    if status == "held":
        print("ATTR: job-state-reasons=job-hold-until-specified", file=sys.stderr)
        if result.get("hold_reason") == "label_limit_exceeded":
            requested = int(result.get("requested_labels") or 0)
            maximum = int(result.get("max_labels") or 0)
            print(
                f"ATTR: job-state-message=PrintHub label limit exceeded: "
                f"{requested} requested, maximum {maximum}",
                file=sys.stderr,
            )
    elif status in {"queued", "processing", "waiting_for_service"}:
        print("ATTR: job-state-reasons=job-queued", file=sys.stderr)
        print(
            "ATTR: job-state-message=PrintHub accepted the job into its durable queue",
            file=sys.stderr,
        )
    if pages:
        print(f"ATTR: job-impressions={pages}", file=sys.stderr)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
