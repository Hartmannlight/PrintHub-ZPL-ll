from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
import uuid

import pytest

from zplgrid import api
from zplgrid.integration_events import (
    IntegrationEventStore,
    IntegrationEventWorker,
    ThingdexEventPublisher,
)


def _payload(event_id: str) -> dict:
    return {
        "event_id": event_id,
        "intent_id": str(uuid.uuid4()),
        "sequence": 1,
        "job_id": str(uuid.uuid4()),
        "job_state": "queued",
        "occurred_at": "2026-09-05T00:00:00+00:00",
        "detail": {},
    }


def test_worker_persists_terminal_failure_without_losing_event(tmp_path) -> None:
    store = IntegrationEventStore(tmp_path / "events")
    event_id = str(uuid.uuid4())
    store.enqueue(_payload(event_id))

    worker = IntegrationEventWorker(
        store,
        lambda _payload: (_ for _ in ()).throw(RuntimeError("Thingdex offline")),
        max_attempts=1,
    )

    assert worker.run_once()
    saved = store.get(event_id)
    assert saved["state"] == "dead"
    assert saved["attempts"] == 1
    assert saved["payload"]["event_id"] == event_id


def test_expired_claim_is_recovered_and_event_ids_reject_conflicts(tmp_path) -> None:
    store = IntegrationEventStore(tmp_path / "events")
    event_id = str(uuid.uuid4())
    payload = _payload(event_id)
    store.enqueue(payload)

    claimed = store.claim_due(lease_seconds=0)
    recovered = store.claim_due()

    assert claimed is not None
    assert recovered is not None
    assert recovered["event_id"] == event_id
    with pytest.raises(ValueError, match="reused with different payload"):
        store.enqueue({**payload, "job_state": "failed"})


def test_publisher_signs_the_exact_transmitted_body(monkeypatch) -> None:
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("zplgrid.integration_events.requests.post", post)
    payload = _payload(str(uuid.uuid4()))
    ThingdexEventPublisher("http://thingdex/events", "shared-secret").publish(payload)

    expected = "sha256=" + hmac.new(
        b"shared-secret", captured["content"], hashlib.sha256
    ).hexdigest()
    assert captured["headers"]["X-Thingdex-Signature"] == expected
    assert json.loads(captured["content"]) == payload


def test_thingdex_job_enqueues_one_deterministic_status_event(tmp_path, monkeypatch) -> None:
    jobs = tmp_path / "jobs"
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(jobs))
    monkeypatch.delenv("PRINTHUB_INTEGRATION_EVENTS_DIR", raising=False)
    template_path = tmp_path / "template.json"
    template_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "Test",
                "layout": {
                    "kind": "leaf",
                    "elements": [{"type": "text", "text": "Hello"}],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        api,
        "load_template_entry",
        lambda _template_id: SimpleNamespace(template_path=template_path),
    )
    monkeypatch.setattr(
        api,
        "print_template",
        lambda printer_id, _payload: api.PrintResponse(
            printer_id=printer_id,
            bytes_sent=12,
            job_id="fleet-delivery",
            job_state="queued",
        ),
    )
    intent_id = str(uuid.uuid4())
    request = api.PrintJobCreateRequest(
        printer_id="demo",
        template_id="asset",
        idempotency_key="thingdex:event-test",
        origin="thingdex",
        origin_reference=intent_id,
    )

    first = api.create_print_job(request)
    second = api.create_print_job(request)

    assert first.id == second.id
    records = list((jobs / "integration-events").glob("*.json"))
    assert len(records) == 1
    record = json.loads(records[0].read_text(encoding="utf-8"))
    assert record["payload"]["intent_id"] == intent_id
    assert record["payload"]["job_id"] == first.id
    assert record["payload"]["sequence"] == 1
    assert record["payload"]["job_state"] == "queued"
