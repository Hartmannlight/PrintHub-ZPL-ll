from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator


CONTRACT = Path(__file__).parents[1] / "contracts" / "print-service-v2"


def _load(name: str):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


def test_protocol_examples_validate_against_their_schemas():
    pairs = [
        ("service.schema.json", "examples/zebra-service.json"),
        ("service.schema.json", "examples/raster-service.json"),
        ("job-submit.schema.json", "examples/job-submit-zpl.json"),
        ("error.schema.json", "examples/error.json"),
    ]
    for schema_name, example_name in pairs:
        Draft202012Validator(_load(schema_name)).validate(_load(example_name))


def test_job_example_checksum_matches_decoded_immutable_artifact():
    request = _load("examples/job-submit-zpl.json")
    artifact = request["artifacts"][0]
    decoded = base64.b64decode(artifact["data_base64"], validate=True)
    assert hashlib.sha256(decoded).hexdigest() == artifact["sha256"]


def test_negative_contract_fixtures_are_rejected():
    schema = Draft202012Validator(_load("job-submit.schema.json"))
    request = _load("examples/job-submit-zpl.json")
    request["copies"] = 0
    assert list(schema.iter_errors(request))
    request = _load("examples/job-submit-zpl.json")
    request["unexpected"] = True
    assert list(schema.iter_errors(request))
