from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class LabelLimit:
    requested_labels: int
    max_labels: int

    @property
    def exceeded(self) -> bool:
        return self.requested_labels > self.max_labels

    @property
    def message(self) -> str:
        return (
            f"Job requests {self.requested_labels} labels, but this PrintHub allows "
            f"at most {self.max_labels} labels per job. Review the document and "
            "explicitly confirm the override to continue."
        )


def configured_max_labels() -> int:
    raw = os.getenv("PRINTHUB_MAX_LABELS_PER_JOB", "25")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("PRINTHUB_MAX_LABELS_PER_JOB must be an integer") from exc
    if not 1 <= value <= 100_000:
        raise ValueError("PRINTHUB_MAX_LABELS_PER_JOB must be between 1 and 100000")
    return value


def evaluate_label_limit(*, pages: int, copies: int) -> LabelLimit:
    if pages < 1 or copies < 1:
        raise ValueError("pages and copies must both be positive")
    return LabelLimit(requested_labels=pages * copies, max_labels=configured_max_labels())
