from __future__ import annotations

from zplgrid.printer_services.registry import PrinterServiceRegistry
from zplgrid.printer_services.ports import ServiceConflict
from fastapi.testclient import TestClient
import pytest
from zplgrid import api


TOKEN = "registry-test-token-123456789"


class Adapter:
    printers_by_url = {}
    unavailable = set()

    def __init__(self, base_url, *, api_token, expected_service_id=None):
        assert api_token == TOKEN
        self.base_url = base_url
        self.expected_service_id = expected_service_id
        self.service_id = base_url.rsplit("/", 1)[-1]

    def get_service(self):
        return {
            "protocol": {"name": "printhub-print-service", "major": 2},
            "service_id": self.service_id,
            "display_name": self.service_id,
        }

    def list_printers(self):
        if self.base_url in self.unavailable:
            raise RuntimeError("offline")
        return [dict(item) for item in self.printers_by_url[self.base_url]]

    def _service_id(self):
        return self.service_id


def _printer(service_id):
    return {
        "id": "same-local-id",
        "service_id": service_id,
        "service_printer_id": "same-local-id",
        "display_name": "Printer",
        "media": {"loaded": None, "revision": None},
    }


def _physical_printer(service_id, local_id, serial):
    value = _printer(service_id)
    value.update(
        id=local_id,
        service_printer_id=local_id,
        driver="zebra",
        identity={"serial_number": {"state": "value", "value": serial}},
    )
    return value


def test_registry_separates_equal_local_ids_and_keeps_offline_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "zplgrid.printer_services.registry.HttpPrintServiceAdapter", Adapter
    )
    registry = PrinterServiceRegistry(tmp_path)
    Adapter.printers_by_url = {
        "http://service/service-a": [_printer("service-a")],
        "http://service/service-b": [_printer("service-b")],
    }
    Adapter.unavailable = set()
    registry.seed_service("a", "http://service/service-a", TOKEN)
    registry.seed_service("b", "http://service/service-b", TOKEN)

    first = registry.list_printers()
    assert len(first) == 2
    assert len({printer["id"] for printer in first}) == 2
    stable_ids = {printer["service_id"]: printer["id"] for printer in first}

    Adapter.unavailable = {"http://service/service-b"}
    restarted = PrinterServiceRegistry(tmp_path)
    second = restarted.list_printers()
    assert {printer["service_id"]: printer["id"] for printer in second} == stable_ids
    offline = next(item for item in second if item["service_id"] == "service-b")
    assert offline["offline"] is True
    assert offline["stale"] is True


def test_duplicate_physical_serial_is_blocked_on_both_delivery_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "zplgrid.printer_services.registry.HttpPrintServiceAdapter", Adapter
    )
    Adapter.printers_by_url = {
        "http://service/service-a": [_physical_printer("service-a", "a", "SERIAL-1")],
        "http://service/service-b": [_physical_printer("service-b", "b", "SERIAL-1")],
    }
    Adapter.unavailable = set()
    registry = PrinterServiceRegistry(tmp_path)
    registry.seed_service("a", "http://service/service-a", TOKEN)
    registry.seed_service("b", "http://service/service-b", TOKEN)

    printers = registry.list_printers()

    assert len(printers) == 2
    assert all(item["identity_conflict"] is True for item in printers)
    assert all(item["enabled"] is False for item in printers)


def test_seed_does_not_overwrite_an_existing_connection(tmp_path):
    registry = PrinterServiceRegistry(tmp_path)
    registry.seed_service("default", "http://original", TOKEN)
    registry.seed_service("default", "http://replacement", TOKEN)
    assert registry.list_services()[0]["base_url"] == "http://original"


def test_catalog_preferences_and_default_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "zplgrid.printer_services.registry.HttpPrintServiceAdapter", Adapter
    )
    Adapter.printers_by_url = {
        "http://service/service-a": [_printer("service-a")],
    }
    Adapter.unavailable = set()
    registry = PrinterServiceRegistry(tmp_path)
    registry.seed_service("a", "http://service/service-a", TOKEN)
    public_id = registry.list_printers()[0]["id"]

    updated = registry.update_printer_catalog(
        public_id, display_name="Packing desk", visible=True, make_default=True
    )
    restarted = PrinterServiceRegistry(tmp_path)
    listed = restarted.list_printers()[0]

    assert updated["default"] is True
    assert listed["display_name"] == "Packing desk"
    assert listed["visible"] is True
    assert restarted.default_printer_id() == public_id

    restarted.update_printer_catalog(public_id, visible=False)
    hidden = PrinterServiceRegistry(tmp_path).list_printers()[0]
    assert hidden["visible"] is False
    assert hidden["enabled"] is False
    assert PrinterServiceRegistry(tmp_path).default_printer_id() is None


def test_service_url_change_verifies_identity_and_keeps_public_id(tmp_path, monkeypatch):
    class MovedAdapter(Adapter):
        identities = {
            "http://old/service": "stable-service",
            "http://new/service": "stable-service",
            "http://wrong/service": "different-service",
        }

        def __init__(self, base_url, *, api_token, expected_service_id=None):
            super().__init__(base_url, api_token=api_token, expected_service_id=expected_service_id)
            self.service_id = self.identities[base_url]

        def get_service(self):
            value = super().get_service()
            if self.expected_service_id and self.service_id != self.expected_service_id:
                raise ServiceConflict("service identity changed")
            return value

    monkeypatch.setattr(
        "zplgrid.printer_services.registry.HttpPrintServiceAdapter", MovedAdapter
    )
    MovedAdapter.printers_by_url = {
        "http://old/service": [_printer("stable-service")],
        "http://new/service": [_printer("stable-service")],
    }
    MovedAdapter.unavailable = set()
    registry = PrinterServiceRegistry(tmp_path)
    registry.seed_service("site", "http://old/service", TOKEN)
    old_id = registry.list_printers()[0]["id"]

    registry.update_service("site", base_url="http://new/service")
    assert registry.list_printers()[0]["id"] == old_id
    assert registry.list_services()[0]["base_url"] == "http://new/service"

    with pytest.raises(ServiceConflict, match="service identity changed"):
        registry.update_service("site", base_url="http://wrong/service")
    assert registry.list_services()[0]["base_url"] == "http://new/service"


def test_service_management_requires_admin_and_never_returns_token(monkeypatch):
    class Managed:
        def add_service(self, display_name, base_url, token):
            assert token == TOKEN
            return {
                "connection_id": "connection",
                "display_name": display_name,
                "base_url": base_url,
                "expected_service_id": "service-a",
                "enabled": True,
            }

    monkeypatch.setattr(api, "_service_registry", lambda: Managed())
    monkeypatch.setenv("PRINTHUB_ADMIN_TOKEN", "admin-token-123456789012345")
    monkeypatch.delenv("PRINTHUB_ADMIN_TOKEN_FILE", raising=False)
    client = TestClient(api.app)
    body = {
        "display_name": "Workshop",
        "base_url": "http://zebra-tamer:8080",
        "token": TOKEN,
    }
    assert client.post("/v1/printer-services", json=body).status_code == 401
    response = client.post(
        "/v1/printer-services",
        json=body,
        headers={"Authorization": "Bearer admin-token-123456789012345"},
    )
    assert response.status_code == 201
    assert "token" not in response.json()


def test_queue_and_maintenance_controls_require_admin(monkeypatch):
    calls = []

    class Managed:
        def set_queue_paused(self, connection_id, printer_id, paused):
            calls.append(("queue", connection_id, printer_id, paused))
            return {"queue_paused": paused}

        def run_maintenance(self, connection_id, printer_id, action):
            calls.append(("maintenance", connection_id, printer_id, action))
            return {"action": action}

        def discover_usb_printers(self, connection_id):
            calls.append(("usb", connection_id))
            return [{"vendor_id": 2655, "product_id": 163, "serial_number": "Z1"}]

    monkeypatch.setattr(api, "_service_registry", lambda: Managed())
    monkeypatch.setenv("PRINTHUB_ADMIN_TOKEN", "admin-token-123456789012345")
    monkeypatch.delenv("PRINTHUB_ADMIN_TOKEN_FILE", raising=False)
    client = TestClient(api.app)
    pause_path = "/v1/printer-services/site/printers/zebra/queue/pause"
    maintenance_path = "/v1/printer-services/site/printers/zebra/maintenance/calibrate-media"
    usb_path = "/v1/printer-services/site/usb-devices"

    assert client.post(pause_path).status_code == 401
    headers = {"Authorization": "Bearer admin-token-123456789012345"}
    assert client.post(pause_path, headers=headers).json() == {"queue_paused": True}
    assert client.post(maintenance_path, headers=headers).json() == {"action": "calibrate-media"}
    assert client.get(usb_path, headers=headers).json()["items"][0]["serial_number"] == "Z1"
    assert calls == [
        ("queue", "site", "zebra", True),
        ("maintenance", "site", "zebra", "calibrate-media"),
        ("usb", "site"),
    ]
