from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Mapping, Sequence
import uuid

from .http import HttpPrintServiceAdapter
from .ports import DeliveryReceipt, PrintArtifact


class PrinterServiceRegistry:
    """Persistent multi-service catalog with stable public printer identities."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "registry.json"
        self.secrets = root / "secrets"
        self._lock = threading.RLock()

    @classmethod
    def from_environment(cls) -> "PrinterServiceRegistry":
        configured = os.getenv("PRINTHUB_PRINTER_SERVICES_DIR", "").strip()
        root = Path(configured) if configured else Path("/data/printer-services")
        registry = cls(root)
        url = os.getenv("PRINTHUB_PRINT_SERVICE_URL", "").strip()
        if url:
            token = HttpPrintServiceAdapter._resolve_token(None)
            registry.seed_service("default", url, token)
        additional = os.getenv("PRINTHUB_ADDITIONAL_PRINT_SERVICES", "").strip()
        if additional:
            entries = json.loads(additional)
            if not isinstance(entries, list):
                raise ValueError("PRINTHUB_ADDITIONAL_PRINT_SERVICES must be a JSON list")
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Each additional print service must be an object")
                token_path = Path(str(entry["token_file"]))
                registry.seed_service(
                    str(entry["connection_id"]),
                    str(entry["url"]),
                    token_path.read_text(encoding="utf-8").strip(),
                )
        return registry

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "version": 1,
            "services": {},
            "printer_ids": {},
            "cached_printers": {},
            "deliveries": {},
            "printer_overrides": {},
            "default_printer_id": None,
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("version") != 1:
            raise RuntimeError("Unsupported print-service registry version")
        base = self._empty()
        base.update(payload)
        return base

    def _save(self, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".registry.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _write_token(self, connection_id: str, token: str) -> Path:
        self.secrets.mkdir(parents=True, exist_ok=True)
        path = self.secrets / f"{connection_id}.token"
        fd, temporary = tempfile.mkstemp(prefix=f".{connection_id}.", dir=self.secrets)
        try:
            try:
                os.chmod(temporary, 0o600)
            except OSError:
                pass
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return path

    def seed_service(self, connection_id: str, url: str, token: str) -> None:
        """Idempotently seed Compose configuration without overwriting UI edits."""
        with self._lock:
            payload = self._load()
            if connection_id in payload["services"]:
                return
            token_path = self._write_token(connection_id, token)
            payload["services"][connection_id] = {
                "connection_id": connection_id,
                "display_name": connection_id,
                "base_url": url.rstrip("/"),
                "expected_service_id": None,
                "token_file": str(token_path),
                "enabled": True,
            }
            self._save(payload)

    def add_service(
        self, display_name: str, base_url: str, token: str
    ) -> dict[str, Any]:
        adapter = HttpPrintServiceAdapter(base_url, api_token=token)
        service = adapter.get_service()
        service_id = str(service["service_id"])
        with self._lock:
            payload = self._load()
            for existing in payload["services"].values():
                if existing.get("expected_service_id") == service_id:
                    raise ValueError("This print service is already connected")
            connection_id = str(uuid.uuid4())
            token_path = self._write_token(connection_id, token)
            record = {
                "connection_id": connection_id,
                "display_name": display_name.strip() or service.get("display_name") or service_id,
                "base_url": base_url.rstrip("/"),
                "expected_service_id": service_id,
                "token_file": str(token_path),
                "enabled": True,
            }
            payload["services"][connection_id] = record
            self._save(payload)
            return self._public_service(record)

    @staticmethod
    def _public_service(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "connection_id",
                "display_name",
                "base_url",
                "expected_service_id",
                "enabled",
            )
        }

    def list_services(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._public_service(record)
                for record in self._load()["services"].values()
            ]

    def set_service_enabled(self, connection_id: str, enabled: bool) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            record["enabled"] = enabled
            self._save(payload)
            return self._public_service(record)

    def update_service(
        self,
        connection_id: str,
        *,
        display_name: str | None = None,
        base_url: str | None = None,
        token: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            next_url = (base_url or str(record["base_url"])).rstrip("/")
            next_token = token or self._token(record)
            if base_url is not None or token is not None:
                service = HttpPrintServiceAdapter(
                    next_url,
                    api_token=next_token,
                    expected_service_id=record.get("expected_service_id"),
                ).get_service()
                if not record.get("expected_service_id"):
                    record["expected_service_id"] = str(service["service_id"])
                record["base_url"] = next_url
                if token is not None:
                    record["token_file"] = str(self._write_token(connection_id, next_token))
            if display_name is not None:
                record["display_name"] = display_name.strip()
            if enabled is not None:
                record["enabled"] = enabled
            self._save(payload)
            return self._public_service(record)

    def save_zebra_printer(
        self, connection_id: str, printer_id: str, config: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            if not record.get("enabled", True):
                raise ValueError("Print service is disabled")
            return self._adapter(record).save_zebra_printer(printer_id, config)

    def load_zebra_media(
        self, connection_id: str, printer_id: str, media: Mapping[str, Any]
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            return self._adapter(record).load_zebra_media(printer_id, media)

    def set_queue_paused(
        self, connection_id: str, printer_id: str, paused: bool
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            return self._adapter(record).set_queue_paused(printer_id, paused)

    def run_maintenance(
        self, connection_id: str, printer_id: str, action: str
    ) -> dict[str, Any]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            return self._adapter(record).run_maintenance(printer_id, action)

    def discover_usb_printers(self, connection_id: str) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._load()
            try:
                record = payload["services"][connection_id]
            except KeyError:
                raise KeyError(connection_id) from None
            return self._adapter(record).discover_usb_printers()

    @staticmethod
    def _token(record: Mapping[str, Any]) -> str:
        return Path(str(record["token_file"])).read_text(encoding="utf-8").strip()

    def _adapter(self, record: Mapping[str, Any]) -> HttpPrintServiceAdapter:
        return HttpPrintServiceAdapter(
            str(record["base_url"]),
            api_token=self._token(record),
            expected_service_id=record.get("expected_service_id"),
        )

    @staticmethod
    def _safe_id(value: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
        return safe or "printer"

    def _public_printer_id(
        self, payload: dict[str, Any], service_id: str, local_id: str
    ) -> str:
        key = f"{service_id}/{local_id}"
        current = payload["printer_ids"].get(key)
        if current:
            return str(current)
        used = set(payload["printer_ids"].values())
        candidate = self._safe_id(local_id)
        if candidate in used:
            candidate = self._safe_id(f"{service_id[:8]}-{local_id}")
        suffix = 2
        unique = candidate
        while unique in used:
            unique = f"{candidate}-{suffix}"
            suffix += 1
        payload["printer_ids"][key] = unique
        return unique

    def _decorate(
        self,
        payload: dict[str, Any],
        connection_id: str,
        printer: Mapping[str, Any],
        *,
        offline: bool,
    ) -> dict[str, Any]:
        service_id = str(printer["service_id"])
        local_id = str(printer["service_printer_id"])
        public_id = self._public_printer_id(payload, service_id, local_id)
        result = dict(printer)
        result["id"] = public_id
        override = payload["printer_overrides"].get(public_id, {})
        if override.get("display_name"):
            result["display_name"] = str(override["display_name"])
        visible = bool(override.get("visible", True))
        result["visible"] = visible
        result["enabled"] = bool(result.get("enabled", True)) and visible
        result["service_connection_id"] = connection_id
        result["offline"] = offline
        result["stale"] = offline
        return result

    def list_printers(self) -> list[dict[str, Any]]:
        with self._lock:
            payload = self._load()
            result: list[dict[str, Any]] = []
            changed = False
            for connection_id, record in payload["services"].items():
                if not record.get("enabled", True):
                    continue
                try:
                    adapter = self._adapter(record)
                    printers = adapter.list_printers()
                    service_id = adapter._service_id()
                    if not record.get("expected_service_id"):
                        record["expected_service_id"] = service_id
                        changed = True
                    payload["cached_printers"][connection_id] = printers
                    changed = True
                    offline = False
                except (OSError, RuntimeError):
                    printers = payload["cached_printers"].get(connection_id, [])
                    offline = True
                result.extend(
                    self._decorate(
                        payload, connection_id, printer, offline=offline
                    )
                    for printer in printers
                )
            physical: dict[tuple[str, str], list[dict[str, Any]]] = {}
            for printer in result:
                serial = (
                    ((printer.get("identity") or {}).get("serial_number") or {}).get("value")
                )
                if serial:
                    key = (str(printer.get("driver") or "unknown"), str(serial))
                    physical.setdefault(key, []).append(printer)
            for duplicates in physical.values():
                if len(duplicates) < 2:
                    continue
                for printer in duplicates:
                    printer["identity_conflict"] = True
                    printer["enabled"] = False
            if changed:
                self._save(payload)
            return result

    def get_printer(self, printer_id: str) -> dict[str, Any]:
        for printer in self.list_printers():
            if printer["id"] == printer_id:
                return printer
        raise KeyError(printer_id)

    def default_printer_id(self) -> str | None:
        with self._lock:
            value = self._load().get("default_printer_id")
            return str(value) if value else None

    def update_printer_catalog(
        self,
        printer_id: str,
        *,
        display_name: str | None = None,
        visible: bool | None = None,
        make_default: bool | None = None,
    ) -> dict[str, Any]:
        printer = self.get_printer(printer_id)
        with self._lock:
            payload = self._load()
            override = payload["printer_overrides"].setdefault(printer_id, {})
            if display_name is not None:
                override["display_name"] = display_name.strip()
            if visible is not None:
                override["visible"] = visible
                if not visible and payload.get("default_printer_id") == printer_id:
                    payload["default_printer_id"] = None
            if make_default is True:
                if visible is False or not bool(override.get("visible", True)):
                    raise ValueError("A hidden printer cannot be the default")
                payload["default_printer_id"] = printer_id
            elif make_default is False and payload.get("default_printer_id") == printer_id:
                payload["default_printer_id"] = None
            self._save(payload)
        updated = dict(printer)
        if display_name is not None:
            updated["display_name"] = display_name.strip()
        if visible is not None:
            updated["visible"] = visible
            updated["enabled"] = bool(updated.get("enabled", True)) and visible
        updated["default"] = self.default_printer_id() == printer_id
        return updated

    def _record_for_printer(
        self, printer: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        connection_id = str(printer["service_connection_id"])
        payload = self._load()
        try:
            record = payload["services"][connection_id]
        except KeyError:
            raise KeyError(connection_id) from None
        return payload, record, connection_id

    def deliver_job(
        self,
        artifacts: Sequence[PrintArtifact],
        printer: Mapping[str, Any],
        *,
        copies: int,
        idempotency_key: str,
        description: str,
        media_revision: str | None = None,
    ) -> DeliveryReceipt:
        with self._lock:
            payload, record, connection_id = self._record_for_printer(printer)
            receipt = self._adapter(record).deliver_job(
                artifacts,
                printer,
                copies=copies,
                idempotency_key=idempotency_key,
                description=description,
                media_revision=media_revision,
            )
            if receipt.delivery_id:
                payload["deliveries"][receipt.delivery_id] = connection_id
                self._save(payload)
            return receipt

    def deliver(
        self, artifact: PrintArtifact, printer: Mapping[str, Any]
    ) -> DeliveryReceipt:
        return self.deliver_job(
            [artifact],
            printer,
            copies=1,
            idempotency_key=artifact.idempotency_key or str(uuid.uuid4()),
            description=artifact.description,
            media_revision=(printer.get("media") or {}).get("revision"),
        )

    def get_deliveries(self, delivery_ids: list[str]) -> dict[str, DeliveryReceipt]:
        with self._lock:
            payload = self._load()
            grouped: dict[str, list[str]] = {}
            for delivery_id in dict.fromkeys(delivery_ids):
                connection_id = payload["deliveries"].get(delivery_id)
                if connection_id:
                    grouped.setdefault(connection_id, []).append(delivery_id)
            result: dict[str, DeliveryReceipt] = {}
            for connection_id, ids in grouped.items():
                record = payload["services"].get(connection_id)
                if record and record.get("enabled", True):
                    result.update(self._adapter(record).get_deliveries(ids))
            return result

    def cancel_deliveries(self, delivery_ids: list[str]) -> dict[str, DeliveryReceipt]:
        with self._lock:
            payload = self._load()
            result: dict[str, DeliveryReceipt] = {}
            for delivery_id in dict.fromkeys(delivery_ids):
                connection_id = payload["deliveries"].get(delivery_id)
                record = payload["services"].get(connection_id) if connection_id else None
                if record is None or not record.get("enabled", True):
                    raise RuntimeError(f"Print service for delivery {delivery_id} is unavailable")
                result[delivery_id] = self._adapter(record).cancel_delivery(delivery_id)
            return result
