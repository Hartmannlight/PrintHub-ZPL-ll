from __future__ import annotations

import base64
import hashlib

import pytest

from zplgrid.printer_services import (
    DeliveryState,
    HttpPrintServiceAdapter,
    PrintArtifact,
    ServiceConflict,
)


TOKEN = "test-print-service-token-123456"


class Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)

    def json(self):
        return self._payload


def test_adapter_verifies_identity_and_normalizes_catalog(monkeypatch):
    replies = iter(
        [
            Response(
                {
                    "protocol": {"name": "printhub-print-service", "major": 2},
                    "service_id": "service-a",
                }
            ),
            Response(
                {
                    "items": [
                        {
                            "id": "local-zebra",
                            "display_name": "Shipping",
                            "device_family": "zebra",
                            "accepted_mime_types": ["application/zpl"],
                            "profile": {"resolution_dpi": 203},
                            "media": {
                                "revision": "media-7",
                                "state": {
                                    "remaining_labels": 42,
                                    "media": {
                                        "width_mm": 50,
                                        "height_mm": 25,
                                        "color": {"name": "yellow", "hex": "#ffdd00"},
                                    },
                                },
                            },
                        }
                    ]
                }
            ),
        ]
    )
    monkeypatch.setattr(
        "zplgrid.printer_services.http.requests.request",
        lambda *_args, **_kwargs: next(replies),
    )
    printer = HttpPrintServiceAdapter(
        "http://zebra-tamer", api_token=TOKEN, expected_service_id="service-a"
    ).list_printers()[0]

    assert printer["service_id"] == "service-a"
    assert printer["service_printer_id"] == "local-zebra"
    assert printer["alignment"]["dpi"] == 203
    assert printer["media"]["loaded"]["remaining_labels"] == 42


def test_adapter_rejects_an_identity_change(monkeypatch):
    monkeypatch.setattr(
        "zplgrid.printer_services.http.requests.request",
        lambda *_args, **_kwargs: Response(
            {
                "protocol": {"name": "printhub-print-service", "major": 2},
                "service_id": "unexpected",
            }
        ),
    )
    adapter = HttpPrintServiceAdapter(
        "http://zebra-tamer", api_token=TOKEN, expected_service_id="expected"
    )
    with pytest.raises(ServiceConflict, match="Expected service"):
        adapter.get_service()


def test_adapter_submits_one_atomic_multi_page_job(monkeypatch):
    captured = {}

    def request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return Response(
            {
                "id": "service-job-1",
                "state": "queued",
                "device_payload_bytes": 123,
                "error": None,
            }
        )

    monkeypatch.setattr("zplgrid.printer_services.http.requests.request", request)
    adapter = HttpPrintServiceAdapter("http://zebra-tamer", api_token=TOKEN)
    pages = [
        PrintArtifact("application/zpl", b"page-a", "document"),
        PrintArtifact("application/zpl", b"page-b", "document"),
    ]
    receipt = adapter.deliver_job(
        pages,
        {"id": "public", "service_printer_id": "local"},
        copies=2,
        idempotency_key="logical-job/attempt-1",
        description="document",
        media_revision="media-7",
    )

    assert captured["url"] == "http://zebra-tamer/v2/printers/local/jobs"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert captured["json"]["copies"] == 2
    assert [
        base64.b64decode(item["data_base64"])
        for item in captured["json"]["artifacts"]
    ] == [b"page-a", b"page-b"]
    assert captured["json"]["artifacts"][0]["sha256"] == hashlib.sha256(
        b"page-a"
    ).hexdigest()
    assert receipt.state is DeliveryState.QUEUED
    assert receipt.delivery_id == "service-job-1"


def test_adapter_uses_v2_admin_and_zebra_extension_routes(monkeypatch):
    requests = []

    def request(method, url, **kwargs):
        requests.append((method, url, kwargs.get("json")))
        if url.endswith("/media"):
            return Response({"remaining_labels": 50})
        if url.endswith("/cancel"):
            return Response({"id": "job-1", "state": "cancelled", "device_payload_bytes": 0})
        if "/maintenance/" in url:
            return Response({"action": "calibrate-media"})
        return Response({"printer": {"id": "local"}})

    monkeypatch.setattr("zplgrid.printer_services.http.requests.request", request)
    adapter = HttpPrintServiceAdapter("http://zebra-tamer", api_token=TOKEN)

    adapter.save_zebra_printer("local", {"transport": "tcp"})
    adapter.load_zebra_media("local", {"width_mm": 50})
    adapter.run_maintenance("local", "calibrate-media")
    cancelled = adapter.cancel_delivery("job-1")

    assert [item[1] for item in requests] == [
        "http://zebra-tamer/v2/extensions/zebra/printers/local",
        "http://zebra-tamer/v2/admin/printers/local/media",
        "http://zebra-tamer/v2/extensions/zebra/printers/local/maintenance/calibrate-media",
        "http://zebra-tamer/v2/jobs/job-1/cancel",
    ]
    assert cancelled.state is DeliveryState.CANCELLED
