from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol


class DeliveryState(str, Enum):
    """Transport state reported by a printer fleet implementation."""

    QUEUED = "queued"
    CONNECTING = "connecting"
    TRANSMITTING = "transmitting"
    TRANSPORT_ACCEPTED = "transport_accepted"
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    FAILED = "failed"
    RETRY_SCHEDULED = "retry_scheduled"


class FleetConflict(RuntimeError):
    """Optimistic-concurrency or idempotency conflict reported by PrinterFleet."""


@dataclass(frozen=True)
class PrintArtifact:
    """Immutable device payload submitted across the fleet boundary."""

    mime_type: str
    payload: bytes
    description: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    """Fleet receipt without claiming that a socket write printed a label."""

    bytes_accepted: int
    state: DeliveryState
    delivery_id: str | None = None
    downstream_state: str | None = None

    def __post_init__(self) -> None:
        if self.bytes_accepted < 0:
            raise ValueError("bytes_accepted must not be negative")

    @property
    def is_physically_confirmed(self) -> bool:
        return self.state is DeliveryState.CONFIRMED


class ArtifactDeliveryPort(Protocol):
    """Submit an already prepared artifact to a physical-delivery boundary."""

    def deliver(
        self,
        artifact: PrintArtifact,
        printer: Mapping[str, Any],
    ) -> DeliveryReceipt: ...


class PrinterCatalogPort(Protocol):
    """Read fleet-owned printer capability snapshots."""

    def list_printers(self) -> list[dict[str, Any]]: ...

    def get_printer(self, printer_id: str) -> dict[str, Any]: ...


class PrinterAdministrationPort(Protocol):
    """Temporary PrintHub compatibility facade for fleet-owned configuration."""

    def put_printer(self, printer_id: str, printer: Mapping[str, Any]) -> dict[str, Any]: ...

    def patch_printer(
        self,
        printer_id: str,
        settings: Mapping[str, Any],
        revision: int,
    ) -> dict[str, Any]: ...


class PrinterFleetPort(
    ArtifactDeliveryPort,
    PrinterCatalogPort,
    PrinterAdministrationPort,
    Protocol,
):
    """Complete boundary used by PrintHub for printer reads and delivery."""
