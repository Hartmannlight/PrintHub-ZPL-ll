from __future__ import annotations

import pytest

from zplgrid.printing.limits import configured_max_labels, evaluate_label_limit


def test_label_limit_counts_pages_times_copies(monkeypatch) -> None:
    monkeypatch.setenv("PRINTHUB_MAX_LABELS_PER_JOB", "25")

    allowed = evaluate_label_limit(pages=5, copies=5)
    blocked = evaluate_label_limit(pages=3, copies=9)

    assert not allowed.exceeded
    assert blocked.exceeded
    assert blocked.requested_labels == 27
    assert "27 labels" in blocked.message
    assert "25 labels" in blocked.message


@pytest.mark.parametrize("value", ["0", "-1", "many", "100001"])
def test_invalid_label_limit_configuration_fails_closed(monkeypatch, value) -> None:
    monkeypatch.setenv("PRINTHUB_MAX_LABELS_PER_JOB", value)

    with pytest.raises(ValueError, match="PRINTHUB_MAX_LABELS_PER_JOB"):
        configured_max_labels()
