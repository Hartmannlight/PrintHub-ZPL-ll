from __future__ import annotations

import base64
import hashlib
import re
from typing import Any, Mapping
import uuid

import requests

from .ports import DeliveryReceipt, DeliveryState, FleetConflict, PrintArtifact


class HttpPrinterFleetAdapter:
    """Versioned HTTP adapter for the independently deployed PrinterFleet."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                timeout=self.timeout_seconds,
                **kwargs,
            )
            if response.status_code == 404:
                raise KeyError(path.rsplit("/", 1)[-1])
            if response.status_code == 409:
                raise FleetConflict(response.text)
            response.raise_for_status()
            return response
        except KeyError:
            raise
        except FleetConflict:
            raise
        except requests.RequestException as exc:
            detail = getattr(exc.response, "text", "") if exc.response is not None else ""
            raise RuntimeError(f"PrinterFleet request failed: {detail or exc}") from exc

    def list_printers(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/v1/printers").json()
        if not isinstance(payload, list):
            raise RuntimeError("PrinterFleet returned an invalid printer list")
        return payload

    def get_printer(self, printer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/printers/{printer_id}").json()

    def put_printer(self, printer_id: str, printer: Mapping[str, Any]) -> dict[str, Any]:
        return self._request(
            "PUT", f"/v1/printers/{printer_id}", json=dict(printer)
        ).json()

    def patch_printer(
        self,
        printer_id: str,
        settings: Mapping[str, Any],
        revision: int,
    ) -> dict[str, Any]:
        return self._request(
            "PATCH",
            f"/v1/printers/{printer_id}",
            json={"revision": revision, "settings": dict(settings)},
        ).json()

    def get_status(self, printer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/printers/{printer_id}/status").json()

    def list_agents(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/agents").json()

    def discover_agents(self, urls: list[str] | None = None) -> dict[str, Any]:
        return self._request(
            "POST", "/v1/agents/discover", json={"urls": urls or []}
        ).json()

    def export_printers(self) -> dict[str, Any]:
        return self._request("GET", "/v1/printer-registry/export").json()

    def import_printers(self, document: Mapping[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", "/v1/printer-registry/import", json=dict(document)
        ).json()

    def register_discovered_printer(
        self,
        *,
        base_url: str,
        printer_id: str,
        expected_agent_id: str | None,
        name: str | None,
    ) -> dict[str, Any]:
        discovery = self.discover_agents([base_url])
        normalized = base_url.rstrip("/")
        agent = next(
            (
                item
                for item in discovery.get("agents", [])
                if item.get("available") and str(item.get("base_url", "")).rstrip("/") == normalized
            ),
            None,
        )
        if agent is None:
            raise RuntimeError("PrintAgent was not available during registration")
        agent_id = str(agent["id"])
        if expected_agent_id and expected_agent_id != agent_id:
            raise FleetConflict("PrintAgent identity changed since discovery")
        device = next(
            (item for item in agent.get("printers", []) if item.get("id") == printer_id),
            None,
        )
        if device is None:
            raise KeyError(printer_id)
        if device.get("registered_id"):
            return self.get_printer(str(device["registered_id"]))
        existing_ids = {printer["id"] for printer in self.list_printers()}
        candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", printer_id).strip("-") or "printer"
        if candidate in existing_ids:
            candidate = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{agent_id}-{printer_id}").strip("-")
        return self._request(
            "POST",
            f"/v1/agents/{agent_id}/printers/{printer_id}/register",
            json={"public_id": candidate, "name": name},
        ).json()

    def deliver(
        self,
        artifact: PrintArtifact,
        printer: Mapping[str, Any],
    ) -> DeliveryReceipt:
        checksum = f"sha256:{hashlib.sha256(artifact.payload).hexdigest()}"
        response = self._request(
            "POST",
            "/v1/deliveries",
            json={
                "printer_id": printer["id"],
                "idempotency_key": artifact.idempotency_key or str(uuid.uuid4()),
                "artifact": {
                    "mime_type": artifact.mime_type,
                    "payload_base64": base64.b64encode(artifact.payload).decode("ascii"),
                    "checksum": checksum,
                    "description": artifact.description,
                },
            },
        ).json()
        state_value = str(response["state"])
        try:
            state = DeliveryState(state_value)
        except ValueError:
            state = DeliveryState.UNCONFIRMED
        return DeliveryReceipt(
            bytes_accepted=int(response.get("bytes_accepted", 0)),
            state=state,
            delivery_id=str(response["id"]),
            downstream_state=state_value,
        )
