from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable
import uuid

import requests


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class IntegrationEventStore:
    """Durable file-backed outbox independent from HTTP delivery."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _event_path(self, event_id: str) -> Path:
        return self.path / f"{uuid.UUID(event_id)}.json"

    @staticmethod
    def _write(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def enqueue(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_id = str(payload["event_id"])
        path = self._event_path(event_id)
        with self._lock:
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing.get("payload") != payload:
                    raise ValueError(f"Integration event id reused with different payload: {event_id}")
                return existing
            now = _now().isoformat()
            record = {
                "event_id": event_id,
                "state": "pending",
                "attempts": 0,
                "next_attempt_at": now,
                "lease_until": None,
                "last_error": None,
                "payload": payload,
                "created_at": now,
                "updated_at": now,
            }
            self._write(path, record)
            return record

    def claim_due(self, *, lease_seconds: int = 300) -> dict[str, Any] | None:
        now = _now()
        with self._lock:
            self.path.mkdir(parents=True, exist_ok=True)
            for path in sorted(self.path.glob("*.json")):
                record = json.loads(path.read_text(encoding="utf-8"))
                due = _parse_time(record.get("next_attempt_at"))
                lease = _parse_time(record.get("lease_until"))
                claimable = record["state"] in {"pending", "retry_scheduled"}
                claimable = claimable and (due is None or due <= now)
                claimable = claimable or (record["state"] == "delivering" and lease and lease <= now)
                if not claimable:
                    continue
                record["state"] = "delivering"
                record["lease_until"] = (now + timedelta(seconds=lease_seconds)).isoformat()
                record["updated_at"] = now.isoformat()
                self._write(path, record)
                return record
        return None

    def complete(self, event_id: str) -> None:
        self._update(event_id, state="delivered", lease_until=None, next_attempt_at=None)

    def fail(self, event_id: str, error: str, *, max_attempts: int = 10) -> None:
        path = self._event_path(event_id)
        with self._lock:
            record = json.loads(path.read_text(encoding="utf-8"))
            attempts = int(record.get("attempts") or 0) + 1
            terminal = attempts >= max_attempts
            record.update(
                state="dead" if terminal else "retry_scheduled",
                attempts=attempts,
                lease_until=None,
                next_attempt_at=None
                if terminal
                else (_now() + timedelta(seconds=min(300, 2 ** min(attempts, 8)))).isoformat(),
                last_error=error[:2000],
                updated_at=_now().isoformat(),
            )
            self._write(path, record)

    def _update(self, event_id: str, **changes: Any) -> None:
        path = self._event_path(event_id)
        with self._lock:
            record = json.loads(path.read_text(encoding="utf-8"))
            record.update(changes, updated_at=_now().isoformat())
            self._write(path, record)

    def get(self, event_id: str) -> dict[str, Any]:
        return json.loads(self._event_path(event_id).read_text(encoding="utf-8"))


class ThingdexEventPublisher:
    def __init__(self, url: str, secret: str, *, timeout_seconds: float = 10) -> None:
        self.url = url
        self.secret = secret.encode()
        self.timeout_seconds = timeout_seconds

    def publish(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = "sha256=" + hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        response = requests.post(
            self.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Thingdex-Signature": signature,
                "X-Correlation-ID": str(payload["event_id"]),
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()


class IntegrationEventWorker:
    def __init__(
        self,
        store: IntegrationEventStore,
        publish: Callable[[dict[str, Any]], None],
        *,
        interval_seconds: float = 1,
        max_attempts: int = 10,
    ) -> None:
        self.store = store
        self.publish = publish
        self.interval_seconds = interval_seconds
        self.max_attempts = max_attempts
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self) -> bool:
        record = self.store.claim_due()
        if record is None:
            return False
        try:
            self.publish(dict(record["payload"]))
        except Exception as exc:
            self.store.fail(record["event_id"], str(exc), max_attempts=self.max_attempts)
        else:
            self.store.complete(record["event_id"])
        return True

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run, name="integration-events", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stopped.wait(self.interval_seconds):
            self.run_once()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread:
            self._thread.join(timeout=max(1, self.interval_seconds + 1))


def event_id(job_id: str, sequence: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"printhub:{job_id}:{sequence}"))
