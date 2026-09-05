import json
from pathlib import Path

from zplgrid.api import app


def test_checked_in_openapi_matches_application_contract() -> None:
    artifact = Path(__file__).resolve().parents[1] / "openapi.json"

    assert json.loads(artifact.read_text(encoding="utf-8")) == app.openapi()
