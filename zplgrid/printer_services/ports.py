from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence


class DeliveryState(str, Enum):
    QUEUED = "queued"
    HELD = "held"
    CONNECTING = "connecting"
    TRANSMITTING = "transmitting"
    TRANSPORT_ACCEPTED = "transport_accepted"
    CONFIRMED = "confirmed"
    UNCONFIRMED = "unconfirmed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_SCHEDULED = "retry_scheduled"


class ServiceConflict(RuntimeError):
    """Identity, revision, or idempotency conflict from a print service."""


class ServiceUnavailable(RuntimeError):
    """The print service cannot currently be reached or is not ready."""


@dataclass(frozen=True)
class PrintArtifact:
    mime_type: str
    payload: bytes
    description: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    bytes_accepted: int
    state: DeliveryState
    delivery_id: str | None = None
    downstream_state: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.bytes_accepted < 0:
            raise ValueError("bytes_accepted must not be negative")

    @property
    def is_physically_confirmed(self) -> bool:
        return self.state is DeliveryState.CONFIRMED


class ArtifactDeliveryPort(Protocol):
    def deliver(
        self, artifact: PrintArtifact, printer: Mapping[str, Any]
    ) -> DeliveryReceipt: ...

    def deliver_job(
        self,
        artifacts: Sequence[PrintArtifact],
        printer: Mapping[str, Any],
        *,
        copies: int,
        idempotency_key: str,
        description: str,
        media_revision: str | None = None,
    ) -> DeliveryReceipt: ...

    def get_deliveries(
        self, delivery_ids: list[str]
    ) -> dict[str, DeliveryReceipt]: ...

    def cancel_deliveries(
        self, delivery_ids: list[str]
    ) -> dict[str, DeliveryReceipt]: ...


class PrinterCatalogPort(Protocol):
    def list_printers(self) -> list[dict[str, Any]]: ...

    def get_printer(self, printer_id: str) -> dict[str, Any]: ...


class PrinterServicePort(ArtifactDeliveryPort, PrinterCatalogPort, Protocol):
    """Manufacturer-neutral boundary from PrintHub to physical print services."""
