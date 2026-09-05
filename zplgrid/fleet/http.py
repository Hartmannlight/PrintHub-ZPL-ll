from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any, Mapping
import uuid

import requests

from .ports import DeliveryReceipt, DeliveryState, FleetConflict, PrintArtifact


class HttpPrinterFleetAdapter:
    """Versioned HTTP adapter for the independently deployed PrinterFleet."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10,
        api_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_token = self._resolve_token(api_token)

    @staticmethod
    def _resolve_token(explicit: str | None) -> str:
        if explicit is not None:
            return explicit.strip()
        inline = os.getenv("PRINTHUB_FLEET_API_TOKEN", "").strip()
        path = os.getenv("PRINTHUB_FLEET_API_TOKEN_FILE", "").strip()
        if inline and path:
            raise ValueError("Configure only one PrintHub Fleet token source")
        token = Path(path).read_text(encoding="utf-8").strip() if path else inline
        if token and (len(token) < 16 or any(character.isspace() for character in token)):
            raise ValueError("PrintHub Fleet token must be at least 16 characters without whitespace")
        return token

    def _request(self, method: str, path: str, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers.setdefault("X-Correlation-ID", str(uuid.uuid4()))
        if self.api_token:
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
