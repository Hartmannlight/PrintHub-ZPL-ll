from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from PIL import Image


TOKEN = "raster-simulator-token-123456"


def _load_app(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTER_TEST_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RASTER_TEST_TOKEN", TOKEN)
    monkeypatch.setenv("RASTER_TEST_DPI", "203")
    monkeypatch.setenv("RASTER_TEST_WIDTH_PX", "9")
    monkeypatch.setenv("RASTER_TEST_HEIGHT_PX", "2")
    path = (
        Path(__file__).parents[1]
        / "simulators"
        / "raster-print-service"
        / "app.py"
    )
    spec = importlib.util.spec_from_file_location("raster_test_service_app", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _headers():
    return {"Authorization": f"Bearer {TOKEN}"}


def _request(key="job-1", packed=b"\x80\x00\x80\x00"):
    raster = json.dumps(
        {
            "version": 1,
            "width_px": 9,
            "height_px": 2,
            "dpi": 203,
            "copies": 1,
            "black_bits_base64": base64.b64encode(packed).decode(),
        },
        separators=(",", ":"),
    ).encode()
    return {
        "idempotency_key": key,
        "copies": 2,
        "artifacts": [
            {
                "mime_type": "application/vnd.printhub.raster-page+json",
                "sha256": hashlib.sha256(raster).hexdigest(),
                "data_base64": base64.b64encode(raster).decode(),
            }
        ],
        "options": {},
    }


def test_simulator_implements_catalog_idempotency_and_exact_png_output(
    tmp_path, monkeypatch
):
    module = _load_app(tmp_path, monkeypatch)
    client = TestClient(module.app)
    assert client.get("/v2/service").status_code == 401
    assert client.get("/v2/printers", headers=_headers()).json()["items"][0][
        "accepted_mime_types"
    ] == ["application/vnd.printhub.raster-page+json"]

    first = client.post(
        "/v2/printers/raster-simulator/jobs", json=_request(), headers=_headers()
    )
    second = client.post(
        "/v2/printers/raster-simulator/jobs", json=_request(), headers=_headers()
    )
    assert first.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert first.json()["simulation"] is True
    outputs = sorted((tmp_path / "output" / first.json()["id"]).glob("*.png"))
    assert len(outputs) == 2
    image = Image.open(outputs[0]).convert("1")
    assert image.size == (9, 2)
    assert image.getpixel((0, 0)) == 0
    assert image.getpixel((1, 0)) != 0


def test_simulator_rejects_invalid_padding_before_creating_a_job(tmp_path, monkeypatch):
    module = _load_app(tmp_path, monkeypatch)
    response = TestClient(module.app).post(
        "/v2/printers/raster-simulator/jobs",
        json=_request(packed=b"\x80\x01\x80\x00"),
        headers=_headers(),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_padding"
    assert not (tmp_path / "jobs").exists()


def test_simulator_can_lose_the_first_response_without_duplicate_output(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTER_TEST_MODE", "lost_response_once")
    module = _load_app(tmp_path, monkeypatch)
    client = TestClient(module.app)
    first = client.post(
        "/v2/printers/raster-simulator/jobs", json=_request(), headers=_headers()
    )
    recovered = client.post(
        "/v2/printers/raster-simulator/jobs", json=_request(), headers=_headers()
    )
    assert first.status_code == 503
    assert recovered.status_code == 202
    assert len(list((tmp_path / "jobs").glob("*.json"))) == 1
    assert len(list((tmp_path / "output" / recovered.json()["id"]).glob("*.png"))) == 2


def test_simulator_exposes_explicit_ambiguous_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("RASTER_TEST_MODE", "outcome_unknown")
    module = _load_app(tmp_path, monkeypatch)
    response = TestClient(module.app).post(
        "/v2/printers/raster-simulator/jobs", json=_request(), headers=_headers()
    )
    assert response.status_code == 202
    assert response.json()["state"] == "outcome_unknown"
    assert response.json()["simulation"] is True
