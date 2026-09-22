import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from zplgrid import print_jobs_store as store


def failed_job(tmp_path, monkeypatch, deliveries):
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path))
    return store.save_job(dict(id=str(uuid.uuid4()), status="failed", dispatch_key="original/artifact-v1",
                               downstream_jobs=deliveries, downstream_job_id=deliveries[0]["id"] if deliveries else None))


def test_concurrent_retries_create_only_one_new_attempt(tmp_path, monkeypatch):
    job = failed_job(tmp_path, monkeypatch, [{"id": "old", "state": "failed"}])
    def retry(_):
        try:
            return store.prepare_retry(job["id"])
        except store.RetryNotAllowed:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [value for value in pool.map(retry, range(2)) if value]
    assert len(attempts) == 1
    assert attempts[0]["dispatch_key"] != job["dispatch_key"]
    assert attempts[0]["downstream_jobs"] == []
    assert attempts[0]["delivery_history"][0]["downstream_jobs"] == job["downstream_jobs"]


def test_stale_reconciliation_cannot_overwrite_new_retry(tmp_path, monkeypatch):
    old = failed_job(tmp_path, monkeypatch, [{"id": "old", "state": "failed"}])
    retried = store.prepare_retry(old["id"])
    result = store.save_reconciled_job(old, expected_dispatch_key=old["dispatch_key"])
    assert result == retried
    assert store.load_job(old["id"])["status"] == "queued"


@pytest.mark.parametrize("state", ["completed_observed", "outcome_unknown", "transmitting", "transport_accepted"])
def test_mixed_delivery_outcome_cannot_be_retried(tmp_path, monkeypatch, state):
    job = failed_job(tmp_path, monkeypatch, [{"id": "failed", "state": "failed"}, {"id": "other", "state": state}])
    with pytest.raises(store.RetryNotAllowed):
        store.prepare_retry(job["id"])
    assert store.load_job(job["id"])["dispatch_key"] == job["dispatch_key"]


def test_no_receipt_retains_key_for_lost_response_deduplication(tmp_path, monkeypatch):
    job = failed_job(tmp_path, monkeypatch, [])
    assert store.prepare_retry(job["id"])["dispatch_key"] == job["dispatch_key"]
