from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from ..printer_io import PrintDispatchResult, apply_printer_settings, dispatch_zpl
from .raster import PreparedRasterPage, encode_zpl_graphic


@dataclass(frozen=True)
class PrintArtifact:
    mime_type: str
    payload: bytes
    description: str


class RasterDriver(Protocol):
    def prepare(self, page: PreparedRasterPage, printer: Mapping[str, Any]) -> PrintArtifact: ...


class PrinterBackend(Protocol):
    def dispatch(self, artifact: PrintArtifact, printer: Mapping[str, Any]) -> PrintDispatchResult: ...


class ZplRasterDriver:
    def prepare(self, page: PreparedRasterPage, printer: Mapping[str, Any]) -> PrintArtifact:
        zpl = encode_zpl_graphic(page)
        configured = apply_printer_settings(zpl, printer, generated=True)
        return PrintArtifact(
            mime_type="application/zpl",
            payload=configured.encode("utf-8"),
            description="Raster document",
        )


class ZplBackend:
    def dispatch(self, artifact: PrintArtifact, printer: Mapping[str, Any]) -> PrintDispatchResult:
        if artifact.mime_type != "application/zpl":
            raise ValueError(f"ZPL backend cannot dispatch {artifact.mime_type}")
        return dispatch_zpl(
            printer,
            artifact.payload.decode("utf-8"),
            description=artifact.description,
        )


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
