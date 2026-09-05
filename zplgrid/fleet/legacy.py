from __future__ import annotations

from typing import Any, Mapping

from ..printer_io import dispatch_zpl
from ..printer_media import resolve_dynamic_printer_media
from ..printer_registry import PrinterRegistry
from .ports import DeliveryReceipt, DeliveryState, PrintArtifact


def _delivery_state(downstream_state: str | None) -> DeliveryState:
    if downstream_state is None:
        return DeliveryState.TRANSPORT_ACCEPTED

    normalized = downstream_state.strip().lower()
    if normalized in {"queued", "pending"}:
        return DeliveryState.QUEUED
    if normalized == "connecting":
        return DeliveryState.CONNECTING
    if normalized in {"transmitting", "sending"}:
        return DeliveryState.TRANSMITTING
    if normalized in {"accepted", "transport_accepted"}:
        return DeliveryState.TRANSPORT_ACCEPTED
    if normalized in {"completed", "confirmed", "done", "printed", "succeeded"}:
        return DeliveryState.CONFIRMED
    if normalized in {"failed", "error"}:
        return DeliveryState.FAILED
    if normalized in {"retry", "retry_scheduled"}:
        return DeliveryState.RETRY_SCHEDULED
    return DeliveryState.UNCONFIRMED


class LegacyFleetAdapter:
    """Adapter around PrintHub's temporary in-process registry and transports.

    New document code depends on fleet ports rather than on RAW TCP or
    ZebraTamer directly. PrinterFleet can replace this adapter without changing
    document preparation.
    """

    def __init__(self, registry: PrinterRegistry | None = None) -> None:
        self._registry = registry

    def _catalog(self) -> PrinterRegistry:
        if self._registry is None:
            self._registry = PrinterRegistry()
            self._registry.initialize()
        return self._registry

    def list_printers(self) -> list[dict[str, Any]]:
        return [resolve_dynamic_printer_media(printer) for printer in self._catalog().list()]

    def get_printer(self, printer_id: str) -> dict[str, Any]:
        return resolve_dynamic_printer_media(self._catalog().get(printer_id))

    def put_printer(self, printer_id: str, printer: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(printer)
        payload["id"] = printer_id
        return self._catalog().create(payload)

    def patch_printer(
        self,
        printer_id: str,
        settings: Mapping[str, Any],
        revision: int,
    ) -> dict[str, Any]:
        return self._catalog().patch(printer_id, dict(settings), revision)

    def deliver(
        self,
        artifact: PrintArtifact,
        printer: Mapping[str, Any],
    ) -> DeliveryReceipt:
        if artifact.mime_type != "application/zpl":
            raise ValueError(f"Legacy fleet cannot deliver {artifact.mime_type}")

        result = dispatch_zpl(
            printer,
            artifact.payload.decode("utf-8"),
            description=artifact.description,
        )
        return DeliveryReceipt(
            bytes_accepted=result.bytes_sent,
            delivery_id=result.job_id,
            state=_delivery_state(result.job_state),
            downstream_state=result.job_state,
        )
