from fastapi.testclient import TestClient

from zplgrid.api import app
from zplgrid.templates_store import validate_template_id


def test_template_id_validation_accepts_slug_ids() -> None:
    assert validate_template_id("container-name") == "container-name"
    assert validate_template_id("a1") == "a1"


def test_template_id_validation_rejects_path_like_ids() -> None:
    invalid_ids = ["../secret", "foo/bar", "bad_id", "-bad", "Bad"]

    for template_id in invalid_ids:
        try:
            validate_template_id(template_id)
        except ValueError:
            continue
        raise AssertionError(f"Expected invalid template id: {template_id}")


def test_template_detail_rejects_invalid_template_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ZPLGRID_PRINT_JOBS_DIR", str(tmp_path / "print-jobs"))
    monkeypatch.setenv("ZPLGRID_DISCOVERY_INTERVAL_SECONDS", "0")
    with TestClient(app) as client:
        response = client.get("/v1/templates/bad_id")

    assert response.status_code == 400, response.text
    assert "template_id must match" in response.json()["detail"]
