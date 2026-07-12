from __future__ import annotations

import json
from types import SimpleNamespace

from zplgrid import api
from zplgrid import print_jobs_store


def test_print_job_is_persisted_and_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps({"schema_version": 1, "name": "Test", "layout": {"kind": "leaf", "elements": [{"type": "text", "text": "Hello"}]}}), encoding="utf-8")
    monkeypatch.setattr(api, "load_template_entry", lambda template_id: SimpleNamespace(template_path=template_path))
    calls: list[str] = []

    def fake_print_template(printer_id, payload):
        calls.append(printer_id)
        return api.PrintResponse(printer_id=printer_id, bytes_sent=12, job_id="downstream-1", job_state="queued")

    monkeypatch.setattr(api, "print_template", fake_print_template)
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


def test_failed_print_job_can_be_retried(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "jobs"))
    template_path = tmp_path / "template.json"
    template_path.write_text(json.dumps({"schema_version": 1, "name": "Test", "layout": {"kind": "leaf", "elements": [{"type": "text", "text": "Hello"}]}}), encoding="utf-8")
    monkeypatch.setattr(api, "load_template_entry", lambda template_id: SimpleNamespace(template_path=template_path))
    outcomes = [api.HTTPException(status_code=502, detail="offline"), api.PrintResponse(printer_id="demo", bytes_sent=12)]

    def fake_print_template(printer_id, payload):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(api, "print_template", fake_print_template)
    failed = api.create_print_job(api.PrintJobCreateRequest(printer_id="demo", template_id="note"))
    retried = api.retry_print_job(failed.id)

    assert failed.status == "failed"
    assert failed.error == "offline"
    assert retried.status == "sent"
    assert retried.attempts == 2


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
