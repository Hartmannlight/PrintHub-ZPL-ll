from __future__ import annotations

import json
import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from zplgrid import api
from zplgrid import print_jobs_store
from zplgrid.printer_services import DeliveryReceipt, DeliveryState


def _zpl_printer(printer_id="demo"):
    return {
        "id": printer_id,
        "enabled": True,
        "accepted_mime_types": ["application/zpl"],
        "media": {
            "revision": "media-1",
            "loaded": {"width_mm": 50, "height_mm": 25, "color": "white"},
        },
        "alignment": {"dpi": 203},
    }


def test_direct_template_print_route_is_not_public() -> None:
    paths = {route.path for route in api.app.routes}
    assert "/v1/printers/{printer_id}/prints/template" not in paths


def test_print_job_is_persisted_and_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps({"schema_version": 1, "name": "Test", "layout": {"kind": "leaf", "elements": [{"type": "text", "text": "Hello"}]}}), encoding="utf-8")
    monkeypatch.setattr(api, "load_template_entry", lambda template_id: SimpleNamespace(template_path=template_path))
    calls: list[str] = []

    class Service:
        def deliver_job(self, artifacts, printer, **kwargs):
            calls.append(printer["id"])
            assert artifacts[0].mime_type == "application/zpl"
            return DeliveryReceipt(12, DeliveryState.QUEUED, "downstream-1", "queued")

        def get_deliveries(self, delivery_ids):
            return {
                "downstream-1": DeliveryReceipt(
                    12, DeliveryState.QUEUED, "downstream-1", "queued"
                )
            }

    service = Service()
    monkeypatch.setattr(api, "_get_printer", lambda printer_id: _zpl_printer(printer_id))
    monkeypatch.setattr(api, "_printer_services", lambda: service)
    request = api.PrintJobCreateRequest(
        printer_id="schildkrote",
        template_id="asset-label",
        variables={"title": "Drill"},
        idempotency_key="thingdex:item:123:create",
        origin="thingdex",
    )

    first = api.create_print_job(request)
    second = api.create_print_job(request)

    assert first.id == second.id
    assert first.status == "queued"
    assert first.downstream_job_id == "downstream-1"
    assert first.attempts == 1
    assert calls == ["schildkrote"]
    assert api.get_print_job(first.id).id == first.id


def test_idempotency_key_rejects_changed_print_content(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    first = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={"serial": "A"},
        target=None,
        idempotency_key="order-123",
        origin="test",
    )
    same = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={"serial": "A"},
        target=None,
        idempotency_key="order-123",
        origin="test",
    )
    assert same["id"] == first["id"]

    with pytest.raises(print_jobs_store.IdempotencyConflict):
        print_jobs_store.create_job(
            printer_id="zebra-1",
            template_id="asset-label",
            variables={"serial": "B"},
            target=None,
            idempotency_key="order-123",
            origin="test",
        )


def test_unknown_outcome_requires_a_separate_artifact_reprint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    original = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={},
        target=None,
        idempotency_key=None,
        origin="test",
    )
    print_jobs_store.save_job_artifacts(
        original["id"],
        {
            "version": 1,
            "copies": 1,
            "media_revision": "media-1",
            "description": "Original bytes",
            "artifacts": [
                {
                    "mime_type": "application/zpl",
                    "data_base64": base64.b64encode(b"^XA^XZ").decode(),
                    "description": "Original bytes",
                }
            ],
        },
    )
    original["status"] = "outcome_unknown"
    print_jobs_store.save_job(original)

    class Service:
        def deliver_job(self, artifacts, _printer, **_kwargs):
            assert artifacts[0].payload == b"^XA^XZ"
            return DeliveryReceipt(6, DeliveryState.QUEUED, "reprint-delivery", "queued")

    monkeypatch.setattr(api, "_get_printer", lambda printer_id: _zpl_printer(printer_id))
    monkeypatch.setattr(api, "_printer_services", lambda: Service())
    reprint = api.reprint_print_job(
        original["id"], api.ReprintRequest(idempotency_key="manual-reprint-1")
    )

    assert reprint.id != original["id"]
    assert reprint.downstream_job_id == "reprint-delivery"
    assert print_jobs_store.load_job(reprint.id)["reprint_of"] == original["id"]


@pytest.mark.parametrize(
    ("service_state", "downstream_state", "expected_status"),
    [
        (DeliveryState.QUEUED, "queued", "queued"),
        (DeliveryState.CONNECTING, "connecting", "queued"),
        (DeliveryState.TRANSMITTING, "transmitting", "queued"),
        (DeliveryState.RETRY_SCHEDULED, "retry_scheduled", "queued"),
        (DeliveryState.TRANSPORT_ACCEPTED, "transport_accepted", "transport_accepted"),
        (DeliveryState.CONFIRMED, "completed_observed", "confirmed"),
        (DeliveryState.HELD, "held", "held"),
        (DeliveryState.CANCELLED, "cancelled", "cancelled"),
        (DeliveryState.UNCONFIRMED, "outcome_unknown", "unconfirmed"),
        (DeliveryState.FAILED, "failed", "failed"),
    ],
)
def test_get_print_job_reconciles_persisted_service_state(
    tmp_path, monkeypatch, service_state, downstream_state, expected_status
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    job = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={},
        target=None,
        idempotency_key=None,
        origin="test",
    )
    job["status"] = "queued"
    job["downstream_job_id"] = "delivery-1"
    job["downstream_job_state"] = "queued"
    print_jobs_store.save_job(job)

    class Service:
        def get_deliveries(self, delivery_ids):
            assert delivery_ids == ["delivery-1"]
            return {
                "delivery-1": DeliveryReceipt(
                    bytes_accepted=42,
                    state=service_state,
                    delivery_id="delivery-1",
                    downstream_state=downstream_state,
                    error="ambiguous transport" if service_state is DeliveryState.UNCONFIRMED else None,
                )
            }

    monkeypatch.setattr(api, "_printer_services", Service)

    reconciled = api.get_print_job(job["id"])

    assert reconciled.status == expected_status
    assert reconciled.downstream_job_state == downstream_state
    assert reconciled.bytes_sent == 42
    assert print_jobs_store.load_job(job["id"])["status"] == expected_status
    if service_state is DeliveryState.UNCONFIRMED:
        assert reconciled.error == "ambiguous transport"


def test_list_print_jobs_batches_reconciliation_and_survives_service_outage(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    for delivery_id in ("delivery-1", "delivery-2"):
        job = print_jobs_store.create_job(
            printer_id="zebra-1",
            template_id="asset-label",
            variables={},
            target=None,
            idempotency_key=None,
            origin="test",
        )
        job["downstream_job_id"] = delivery_id
        print_jobs_store.save_job(job)

    class Service:
        calls = []

        def get_deliveries(self, delivery_ids):
            self.calls.append(delivery_ids)
            raise RuntimeError("Print service is temporarily unavailable")

    service = Service()
    monkeypatch.setattr(api, "_printer_services", lambda: service)

    jobs = api.get_print_jobs()

    assert len(jobs) == 2
    assert all(job.status == "queued" for job in jobs)
    assert len(service.calls) == 1
    assert set(service.calls[0]) == {"delivery-1", "delivery-2"}


def test_multi_delivery_job_exposes_and_aggregates_every_service_state(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    job = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={},
        target=None,
        idempotency_key=None,
        origin="test",
    )
    job["downstream_job_id"] = "delivery-1"
    job["downstream_job_state"] = "queued"
    job["downstream_jobs"] = [
        {"id": "delivery-1", "state": "queued", "bytes_accepted": 0},
        {"id": "delivery-2", "state": "queued", "bytes_accepted": 0},
    ]
    print_jobs_store.save_job(job)

    class Service:
        def get_deliveries(self, delivery_ids):
            assert delivery_ids == ["delivery-1", "delivery-2"]
            return {
                "delivery-1": DeliveryReceipt(
                    bytes_accepted=41,
                    state=DeliveryState.TRANSPORT_ACCEPTED,
                    delivery_id="delivery-1",
                    downstream_state="transport_accepted",
                ),
                "delivery-2": DeliveryReceipt(
                    bytes_accepted=43,
                    state=DeliveryState.UNCONFIRMED,
                    delivery_id="delivery-2",
                    downstream_state="unconfirmed",
                    error="connection lost during transmission",
                ),
            }

    monkeypatch.setattr(api, "_printer_services", Service)

    reconciled = api.get_print_job(job["id"])

    assert reconciled.status == "unconfirmed"
    assert reconciled.bytes_sent == 84
    assert reconciled.downstream_job_id == "delivery-1"
    assert reconciled.downstream_job_state == "transport_accepted"
    assert [item.id for item in reconciled.downstream_jobs] == [
        "delivery-1",
        "delivery-2",
    ]
    assert [item.state for item in reconciled.downstream_jobs] == [
        "transport_accepted",
        "unconfirmed",
    ]
    assert reconciled.error == "connection lost during transmission"


def test_failed_print_job_can_be_retried(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps({"schema_version": 1, "name": "Test", "layout": {"kind": "leaf", "elements": [{"type": "text", "text": "Hello"}]}}), encoding="utf-8")
    monkeypatch.setattr(api, "load_template_entry", lambda template_id: SimpleNamespace(template_path=template_path))
    outcomes = [RuntimeError("offline"), DeliveryReceipt(12, DeliveryState.QUEUED)]

    class Service:
        def deliver_job(self, artifacts, printer, **kwargs):
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(api, "_get_printer", lambda printer_id: _zpl_printer(printer_id))
    monkeypatch.setattr(api, "_printer_services", lambda: Service())
    failed = api.create_print_job(api.PrintJobCreateRequest(printer_id="demo", template_id="note"))
    retried = api.retry_print_job(failed.id)

    assert failed.status == "failed"
    assert failed.error == "offline"
    assert retried.status == "sent"
    assert retried.attempts == 2


def test_unsent_print_job_can_be_cancelled_without_service_io(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    job = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={},
        target=None,
        idempotency_key="cancel-before-send",
        origin="test",
    )

    cancelled = api.cancel_print_job(job["id"])

    assert cancelled.status == "cancelled"
    assert cancelled.downstream_job_id is None
    assert print_jobs_store.load_job(job["id"])["status"] == "cancelled"


def test_cancelled_stale_worker_item_cannot_be_claimed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    stale = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={},
        target=None,
        idempotency_key="cancel-race",
        origin="test",
    )
    api.cancel_print_job(stale["id"])

    result = api._process_stored_print_job(stale)

    assert result["status"] == "cancelled"
    assert result["attempts"] == 0


def test_downstream_print_job_cancellation_uses_original_delivery_id(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    job = print_jobs_store.create_job(
        printer_id="zebra-1",
        template_id="asset-label",
        variables={},
        target=None,
        idempotency_key="cancel-after-send",
        origin="test",
    )
    job.update(
        status="queued",
        downstream_job_id="physical-1",
        downstream_job_state="queued",
        downstream_jobs=[
            {"id": "physical-1", "state": "queued", "bytes_accepted": 0, "error": None}
        ],
    )
    print_jobs_store.save_job(job)

    class Service:
        def get_deliveries(self, delivery_ids):
            return {
                "physical-1": DeliveryReceipt(
                    0, DeliveryState.QUEUED, "physical-1", "queued"
                )
            }

        def cancel_deliveries(self, delivery_ids):
            assert delivery_ids == ["physical-1"]
            return {
                "physical-1": DeliveryReceipt(
                    0, DeliveryState.CANCELLED, "physical-1", "cancelled"
                )
            }

    monkeypatch.setattr(api, "_printer_services", lambda: Service())
    cancelled = api.cancel_print_job(job["id"])

    assert cancelled.status == "cancelled"
    assert cancelled.downstream_job_state == "cancelled"


def test_inline_template_is_snapshotted_in_durable_job(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))

    class Service:
        def deliver_job(self, artifacts, printer, **kwargs):
            return DeliveryReceipt(12, DeliveryState.QUEUED)

    monkeypatch.setattr(api, "_get_printer", lambda printer_id: _zpl_printer(printer_id))
    monkeypatch.setattr(api, "_printer_services", lambda: Service())
    template = {
        "schema_version": 1,
        "name": "Unsaved draft",
        "layout": {"kind": "leaf", "elements": [{"type": "text", "text": "Hello"}]},
    }
    created = api.create_print_job(
        api.PrintJobCreateRequest(
            printer_id="demo",
            template=template,
            variables={"title": "Draft"},
            origin="printhub-studio",
        )
    )

    stored = print_jobs_store.load_job(created.id)
    assert created.source_kind == "inline_template"
    assert stored["template"] == template
    assert stored["resolved_template"] == template
    artifact_set = print_jobs_store.load_job_artifacts(created.id)
    assert artifact_set is not None
    assert artifact_set["artifacts"][0]["mime_type"] == "application/zpl"


@pytest.mark.parametrize(
    ("template_id", "template"),
    [(None, None), ("saved", {"schema_version": 1})],
)
def test_print_job_requires_exactly_one_template_source(template_id, template) -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        api.PrintJobCreateRequest(
            printer_id="demo",
            template_id=template_id,
            template=template,
        )


def test_interrupted_job_requires_explicit_retry(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    job = print_jobs_store.create_job(
        printer_id="demo",
        template_id="note",
        variables={},
        target=None,
        idempotency_key=None,
        origin="test",
    )
    job["status"] = "processing"
    print_jobs_store.save_job(job)

    assert print_jobs_store.recover_interrupted_jobs() == 1
    recovered = print_jobs_store.load_job(job["id"])
    assert recovered["status"] == "outcome_unknown"
    assert "verify the printer" in recovered["error"]
    with pytest.raises(api.HTTPException) as exc:
        api.retry_print_job(job["id"])
    assert exc.value.status_code == 409


def test_recovery_scans_more_than_two_hundred_jobs_without_history_limit(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    interrupted_ids = []
    for index in range(205):
        job = print_jobs_store.create_job(
            printer_id="demo",
            template_id="note",
            variables={"index": index},
            target=None,
            idempotency_key=f"recovery-{index}",
            origin="test",
        )
        job["status"] = "processing"
        print_jobs_store.save_job(job)
        interrupted_ids.append(job["id"])

    assert print_jobs_store.recover_interrupted_jobs() == 205
    assert all(
        print_jobs_store.load_job(job_id)["status"] == "outcome_unknown"
        for job_id in interrupted_ids
    )


def test_template_is_rendered_once_to_raster_for_a_raster_only_service(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    printer = _zpl_printer("image-printer")
    printer["accepted_mime_types"] = [
        "application/vnd.printhub.raster-page+json"
    ]
    captured = []

    class Service:
        def deliver_job(self, artifacts, selected, **kwargs):
            captured.append((artifacts, kwargs))
            return DeliveryReceipt(100, DeliveryState.QUEUED, "raster-job", "queued")

    def render(*_args, **_kwargs):
        stream = BytesIO()
        Image.new("RGB", (400, 200), "white").save(stream, format="PNG")
        return stream.getvalue()

    monkeypatch.setattr(api, "_get_printer", lambda _printer_id: printer)
    monkeypatch.setattr(api, "_printer_services", lambda: Service())
    monkeypatch.setattr(api, "render_labelary_png_bytes", render)
    template = {
        "schema_version": 1,
        "name": "Raster target",
        "layout": {"kind": "leaf", "elements": [{"type": "text", "text": "Hello"}]},
    }
    result = api.create_print_job(
        api.PrintJobCreateRequest(printer_id="image-printer", template=template)
    )

    assert result.status == "queued"
    artifacts, options = captured[0]
    assert artifacts[0].mime_type == "application/vnd.printhub.raster-page+json"
    raster = json.loads(artifacts[0].payload)
    assert raster["copies"] == 1
    assert options["media_revision"] == "media-1"


def test_zebra_with_both_formats_can_explicitly_use_whole_label_raster(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    printer = _zpl_printer("zebra-image-mode")
    printer["accepted_mime_types"] = [
        "application/zpl",
        "application/vnd.printhub.raster-page+json",
    ]
    captured = []

    class Service:
        def deliver_job(self, artifacts, selected, **kwargs):
            captured.append(artifacts)
            return DeliveryReceipt(100, DeliveryState.QUEUED, "raster-job", "queued")

    def render(*_args, **_kwargs):
        stream = BytesIO()
        Image.new("RGB", (400, 200), "white").save(stream, format="PNG")
        return stream.getvalue()

    monkeypatch.setattr(api, "_get_printer", lambda _printer_id: printer)
    monkeypatch.setattr(api, "_printer_services", lambda: Service())
    monkeypatch.setattr(api, "render_labelary_png_bytes", render)
    result = api.create_print_job(
        api.PrintJobCreateRequest(
            printer_id="zebra-image-mode",
            template={
                "schema_version": 1,
                "name": "Whole-label image mode",
                "layout": {
                    "kind": "leaf",
                    "elements": [{"type": "text", "text": "Hello"}],
                },
            },
            output_mode="raster",
        )
    )

    assert result.status == "queued"
    assert captured[0][0].mime_type == "application/vnd.printhub.raster-page+json"


def test_explicit_output_mode_rejects_a_format_the_printer_does_not_accept(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    printer = _zpl_printer("raster-only")
    printer["accepted_mime_types"] = [
        "application/vnd.printhub.raster-page+json"
    ]
    monkeypatch.setattr(api, "_get_printer", lambda _printer_id: printer)

    result = api.create_print_job(
        api.PrintJobCreateRequest(
            printer_id="raster-only",
            template={
                "schema_version": 1,
                "name": "Unsupported native mode",
                "layout": {
                    "kind": "leaf",
                    "elements": [{"type": "text", "text": "Hello"}],
                },
            },
            output_mode="native",
        )
    )

    assert result.status == "failed"
    assert result.error == "The selected printer does not accept native ZPL"


def test_output_mode_is_part_of_the_idempotency_fingerprint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    common = {
        "printer_id": "zebra-1",
        "template_id": "asset-label",
        "variables": {},
        "target": None,
        "idempotency_key": "same-label-different-format",
        "origin": "test",
    }
    print_jobs_store.create_job(**common, output_mode="auto")

    with pytest.raises(print_jobs_store.IdempotencyConflict):
        print_jobs_store.create_job(**common, output_mode="raster")
