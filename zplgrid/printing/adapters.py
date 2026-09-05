from __future__ import annotations

from typing import Any, Mapping, Protocol

from ..fleet.legacy import LegacyFleetAdapter
from ..fleet.ports import ArtifactDeliveryPort, DeliveryReceipt, PrintArtifact
from ..printer_io import apply_printer_settings
from .raster import PreparedRasterPage, encode_zpl_graphic


class RasterDriver(Protocol):
    def prepare(self, page: PreparedRasterPage, printer: Mapping[str, Any]) -> PrintArtifact: ...


class PrinterBackend(ArtifactDeliveryPort, Protocol):
    """Deprecated name retained while callers migrate to ArtifactDeliveryPort."""


class ZplRasterDriver:
    def prepare(self, page: PreparedRasterPage, printer: Mapping[str, Any]) -> PrintArtifact:
        zpl = encode_zpl_graphic(page)
        configured = apply_printer_settings(zpl, printer, generated=True)
        return PrintArtifact(
            mime_type="application/zpl",
            payload=configured.encode("utf-8"),
            description="Raster document",
        )


class ZplBackend(LegacyFleetAdapter):
    """Compatibility adapter for the legacy in-process fleet implementation."""

    def dispatch(self, artifact: PrintArtifact, printer: Mapping[str, Any]) -> DeliveryReceipt:
        return self.deliver(artifact, printer)


def raster_driver_for(printer: Mapping[str, Any]) -> RasterDriver:
    driver = str(printer.get("driver") or "").strip().lower()
    if driver == "zpl":
        return ZplRasterDriver()
    raise ValueError(f"Printer driver does not support raster documents: {driver or 'unset'}")


def backend_for(printer: Mapping[str, Any]) -> PrinterBackend:
    protocol = str((printer.get("connection") or {}).get("protocol") or "").strip().lower()
    if protocol in {"raw9100", "zebra_tamer"}:
        return ZplBackend()
    raise ValueError(f"Printer backend does not support protocol: {protocol or 'unset'}")
