from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
import uuid

import requests

from .ports import DeliveryReceipt, DeliveryState, PrintArtifact, ServiceConflict, ServiceUnavailable


class HttpPrintServiceAdapter:
    """Client for one Print Service Protocol v2 endpoint."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10,
        api_token: str | None = None,
        expected_service_id: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("Print service URL is required")
        self.timeout_seconds = timeout_seconds
        self.api_token = self._resolve_token(api_token)
        self.expected_service_id = expected_service_id
        self._service: dict[str, Any] | None = None

    @staticmethod
    def _resolve_token(explicit: str | None) -> str:
        if explicit is not None:
            token = explicit.strip()
        else:
            inline = os.getenv("PRINTHUB_PRINT_SERVICE_TOKEN", "").strip()
            path = os.getenv("PRINTHUB_PRINT_SERVICE_TOKEN_FILE", "").strip()
            if inline and path:
                raise ValueError("Configure only one PrintHub print-service token source")
            token = Path(path).read_text(encoding="utf-8").strip() if path else inline
        if len(token) < 24 or any(character.isspace() for character in token):
            raise ValueError(
                "Print service token must be at least 24 characters without whitespace"
            )
        return token

    def _request(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("X-Correlation-ID", str(uuid.uuid4()))
        headers.setdefault("Authorization", f"Bearer {self.api_token}")
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                headers=headers,
                **kwargs,
            )
            if response.status_code == 404:
                raise KeyError(path.rsplit("/", 1)[-1])
            if response.status_code == 409:
                raise ServiceConflict(response.text)
            response.raise_for_status()
            return response
        except (KeyError, ServiceConflict):
            raise
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "") if exc.response is not None else ""
            if exc.response is None or exc.response.status_code >= 500:
                raise ServiceUnavailable(
                    f"Print service is unavailable: {detail or exc}"
                ) from exc
            raise RuntimeError(f"Print service request failed: {detail or exc}") from exc

    def get_service(self) -> dict[str, Any]:
        payload = self._request("GET", "/v2/service").json()
        protocol = payload.get("protocol") if isinstance(payload, dict) else None
        if not isinstance(protocol, dict) or protocol.get("major") != 2:
            raise RuntimeError("Endpoint does not implement Print Service Protocol v2")
        service_id = str(payload.get("service_id") or "")
        if not service_id:
            raise RuntimeError("Print service returned no stable service_id")
        if self.expected_service_id and service_id != self.expected_service_id:
            raise ServiceConflict(
                f"Expected service {self.expected_service_id!r}, got {service_id!r}"
            )
        self._service = payload
        return payload

    def _service_id(self) -> str:
        return str((self._service or self.get_service())["service_id"])

    @staticmethod
    def _normalize_printer(payload: Mapping[str, Any], service_id: str) -> dict[str, Any]:
        local_id = str(payload["id"])
        profile = payload.get("profile") or {}
        media_container = payload.get("media") or {}
        media_state = media_container.get("state") or {}
        definition = media_state.get("media") or {}
        color = definition.get("color") or {}
        loaded = None
        if definition:
            loaded = {
                **definition,
                "color": color.get("name") or "unknown",
                "color_hex": color.get("hex"),
                "remaining_labels": media_state.get("remaining_labels"),
            }
        return {
            "id": local_id,
            "display_name": payload.get("display_name") or local_id,
            "enabled": bool(payload.get("enabled", True)),
            "driver": payload.get("device_family") or "generic",
            "accepted_mime_types": list(payload.get("accepted_mime_types") or []),
            "capabilities": payload.get("capabilities") or {},
            "media": {"loaded": loaded, "revision": media_container.get("revision")},
            "alignment": {"dpi": profile.get("resolution_dpi")},
            "profile": profile,
            "identity": payload.get("identity") or {},
            "status": payload.get("status") or {},
            "jobs": payload.get("jobs") or {},
            "observed_at": payload.get("observed_at"),
            "service_id": service_id,
            "service_printer_id": local_id,
        }

    def list_printers(self) -> list[dict[str, Any]]:
        service_id = self._service_id()
        payload = self._request("GET", "/v2/printers").json()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("Print service returned an invalid printer list")
        return [self._normalize_printer(item, service_id) for item in items]

    def get_printer(self, printer_id: str) -> dict[str, Any]:
        service_id = self._service_id()
        payload = self._request("GET", f"/v2/printers/{printer_id}").json()
        return self._normalize_printer(payload, service_id)

    @staticmethod
    def _delivery_receipt(payload: Mapping[str, Any]) -> DeliveryReceipt:
        remote_state = str(payload.get("state") or "outcome_unknown")
        state_map = {
            "queued": DeliveryState.QUEUED,
            "held": DeliveryState.HELD,
            "receiving": DeliveryState.CONNECTING,
            "writing": DeliveryState.TRANSMITTING,
            "verifying": DeliveryState.TRANSMITTING,
            "transport_accepted": DeliveryState.TRANSPORT_ACCEPTED,
            "completed_observed": DeliveryState.CONFIRMED,
            "failed": DeliveryState.FAILED,
            "cancelled": DeliveryState.CANCELLED,
            "outcome_unknown": DeliveryState.UNCONFIRMED,
        }
        return DeliveryReceipt(
            bytes_accepted=int(payload.get("device_payload_bytes") or 0),
            state=state_map.get(remote_state, DeliveryState.UNCONFIRMED),
            delivery_id=str(payload["id"]) if payload.get("id") else None,
            downstream_state=remote_state,
            error=str(payload["error"]) if payload.get("error") else None,
        )

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
        if not artifacts:
            raise ValueError("A print-service job requires at least one artifact")
        local_id = str(printer.get("service_printer_id") or printer["id"])
        body = {
            "idempotency_key": idempotency_key,
            "description": description,
            "media_revision": media_revision,
            "copies": copies,
            "artifacts": [
                {
                    "mime_type": artifact.mime_type,
                    "sha256": hashlib.sha256(artifact.payload).hexdigest(),
                    "data_base64": base64.b64encode(artifact.payload).decode("ascii"),
                }
                for artifact in artifacts
            ],
            "options": {},
        }
        response = self._request(
            "POST", f"/v2/printers/{local_id}/jobs", json=body
        ).json()
        return self._delivery_receipt(response)

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

    def get_deliveries(
        self, delivery_ids: list[str]
    ) -> dict[str, DeliveryReceipt]:
        receipts: dict[str, DeliveryReceipt] = {}
        for delivery_id in dict.fromkeys(delivery_ids):
            try:
                payload = self._request("GET", f"/v2/jobs/{delivery_id}").json()
            except KeyError:
                continue
            receipts[delivery_id] = self._delivery_receipt(payload)
        return receipts

    def cancel_delivery(self, delivery_id: str) -> DeliveryReceipt:
        payload = self._request("POST", f"/v2/jobs/{delivery_id}/cancel").json()
        return self._delivery_receipt(payload)

    def save_zebra_printer(self, printer_id: str, config: Mapping[str, Any]) -> dict[str, Any]:
        response = self._request(
            "POST", f"/v2/extensions/zebra/printers/{printer_id}", json=dict(config)
        ).json()
        if not isinstance(response, dict) or not isinstance(response.get("printer"), dict):
            raise RuntimeError("Print service returned an invalid printer configuration")
        return dict(response["printer"])

    def load_zebra_media(self, printer_id: str, media: Mapping[str, Any]) -> dict[str, Any]:
        response = self._request(
            "PUT", f"/v2/admin/printers/{printer_id}/media", json=dict(media)
        ).json()
        if not isinstance(response, dict):
            raise RuntimeError("Print service returned an invalid media state")
        return response

    def set_queue_paused(self, printer_id: str, paused: bool) -> dict[str, Any]:
        action = "pause" if paused else "resume"
        payload = self._request(
            "POST", f"/v2/printers/{printer_id}/queue/{action}"
        ).json()
        if not isinstance(payload, dict):
            raise RuntimeError("Print service returned an invalid queue state")
        return payload

    def run_maintenance(self, printer_id: str, action: str) -> dict[str, Any]:
        payload = self._request(
            "POST", f"/v2/extensions/zebra/printers/{printer_id}/maintenance/{action}"
        ).json()
        if not isinstance(payload, dict):
            raise RuntimeError("Print service returned an invalid maintenance result")
        return payload

    def discover_usb_printers(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v2/admin/usb-devices").json()
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("Print service returned an invalid USB device list")
        return [dict(item) for item in items if isinstance(item, dict)]
