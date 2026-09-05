from __future__ import annotations

import pytest

from zplgrid.fleet.legacy import LegacyFleetAdapter
from zplgrid.fleet.ports import DeliveryReceipt, DeliveryState, PrintArtifact
from zplgrid.printer_io import PrintDispatchResult


def _artifact() -> PrintArtifact:
    return PrintArtifact("application/zpl", b"^XA^XZ", "test label")


def _raw_printer() -> dict:
    return {
        "id": "network-zebra",
        "connection": {
            "protocol": "raw9100",
            "host": "printer.example.test",
            "port": 9100,
        },
    }


def test_raw_socket_success_is_not_physical_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        "zplgrid.fleet.legacy.dispatch_zpl",
        lambda *_args, **_kwargs: PrintDispatchResult(bytes_sent=7),
    )

    receipt = LegacyFleetAdapter().deliver(_artifact(), _raw_printer())

    assert receipt.bytes_accepted == 7
    assert receipt.state is DeliveryState.TRANSPORT_ACCEPTED
    assert receipt.is_physically_confirmed is False


def test_explicit_downstream_completion_is_physical_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        "zplgrid.fleet.legacy.dispatch_zpl",
        lambda *_args, **_kwargs: PrintDispatchResult(
            bytes_sent=7,
            job_id="delivery-42",
            job_state="completed",
        ),
    )

    receipt = LegacyFleetAdapter().deliver(_artifact(), _raw_printer())

    assert receipt == DeliveryReceipt(
        bytes_accepted=7,
        delivery_id="delivery-42",
        state=DeliveryState.CONFIRMED,
        downstream_state="completed",
    )
    assert receipt.is_physically_confirmed is True


def test_unknown_downstream_state_remains_unconfirmed(monkeypatch) -> None:
    monkeypatch.setattr(
        "zplgrid.fleet.legacy.dispatch_zpl",
        lambda *_args, **_kwargs: PrintDispatchResult(
            bytes_sent=7,
            job_id="delivery-43",
            job_state="vendor-specific-state",
        ),
    )

    receipt = LegacyFleetAdapter().deliver(_artifact(), _raw_printer())

    assert receipt.state is DeliveryState.UNCONFIRMED
    assert receipt.downstream_state == "vendor-specific-state"


def test_legacy_fleet_rejects_non_zpl_artifacts() -> None:
    artifact = PrintArtifact("image/png", b"not-a-printer-payload", "image")

    with pytest.raises(ValueError, match="image/png"):
        LegacyFleetAdapter().deliver(artifact, _raw_printer())
