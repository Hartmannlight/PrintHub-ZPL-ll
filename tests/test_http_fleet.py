from __future__ import annotations

import base64

import pytest

from zplgrid.fleet import DeliveryState, HttpPrinterFleetAdapter, PrintArtifact


class Response:
    def __init__(self, payload):
        self._payload = payload
        self.text = ""
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_http_fleet_sends_versioned_artifact_contract(monkeypatch):
    captured = {}

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return Response({"id": "delivery-1", "state": "queued", "bytes_accepted": 0})

    monkeypatch.setattr("zplgrid.fleet.http.requests.request", request)
    adapter = HttpPrinterFleetAdapter("http://fleet:8000/")
    receipt = adapter.deliver(
        PrintArtifact("application/zpl", b"^XA^XZ", "label", "job-1/attempt-1"),
        {"id": "zebra-1"},
    )

    assert captured["url"] == "http://fleet:8000/v1/deliveries"
    assert captured["json"]["idempotency_key"] == "job-1/attempt-1"
    assert captured["headers"]["X-Correlation-ID"]
    assert base64.b64decode(captured["json"]["artifact"]["payload_base64"]) == b"^XA^XZ"
    assert receipt.state is DeliveryState.QUEUED
    assert receipt.bytes_accepted == 0
    assert receipt.delivery_id == "delivery-1"


def test_unknown_remote_state_is_never_reported_as_confirmed(monkeypatch):
    monkeypatch.setattr(
        "zplgrid.fleet.http.requests.request",
        lambda *_args, **_kwargs: Response(
            {"id": "delivery-2", "state": "vendor_magic", "bytes_accepted": 3}
        ),
    )
    receipt = HttpPrinterFleetAdapter("http://fleet").deliver(
        PrintArtifact("application/zpl", b"zpl", "label"),
        {"id": "zebra-1"},
    )
    assert receipt.state is DeliveryState.UNCONFIRMED


def test_missing_printer_is_exposed_as_catalog_miss(monkeypatch):
    response = Response({"detail": "not found"})
    response.status_code = 404
    monkeypatch.setattr(
        "zplgrid.fleet.http.requests.request", lambda *_args, **_kwargs: response
    )
    try:
        HttpPrinterFleetAdapter("http://fleet").get_printer("missing")
    except KeyError as exc:
        assert exc.args == ("missing",)
    else:
        raise AssertionError("Expected missing fleet printer to raise KeyError")


def test_http_fleet_sends_configured_service_credential(monkeypatch):
    captured = {}

    def request(_method, _url, **kwargs):
        captured.update(kwargs)
        return Response([])

    monkeypatch.setattr("zplgrid.fleet.http.requests.request", request)
    HttpPrinterFleetAdapter("http://fleet", api_token="fleet-secret").list_printers()

    assert captured["headers"]["Authorization"] == "Bearer fleet-secret"


def test_http_fleet_adapter_cannot_administer_physical_devices():
    adapter = HttpPrinterFleetAdapter("http://fleet", api_token="fleet-secret")

    for operation in (
        "put_printer",
        "patch_printer",
        "get_status",
        "list_agents",
        "discover_agents",
        "export_printers",
        "import_printers",
        "register_discovered_printer",
    ):
        assert not hasattr(adapter, operation)


def test_http_fleet_reads_token_from_mounted_secret(tmp_path, monkeypatch):
    token_file = tmp_path / "fleet-token"
    token_file.write_text("mounted-fleet-token-123\n", encoding="utf-8")
    monkeypatch.delenv("PRINTHUB_FLEET_API_TOKEN", raising=False)
    monkeypatch.setenv("PRINTHUB_FLEET_API_TOKEN_FILE", str(token_file))

    adapter = HttpPrinterFleetAdapter("http://fleet")

    assert adapter.api_token == "mounted-fleet-token-123"


def test_http_fleet_rejects_ambiguous_token_sources(tmp_path, monkeypatch):
    token_file = tmp_path / "fleet-token"
    token_file.write_text("mounted-fleet-token-123", encoding="utf-8")
    monkeypatch.setenv("PRINTHUB_FLEET_API_TOKEN", "inline-fleet-token-123")
    monkeypatch.setenv("PRINTHUB_FLEET_API_TOKEN_FILE", str(token_file))

    with pytest.raises(ValueError, match="only one"):
        HttpPrinterFleetAdapter("http://fleet")
