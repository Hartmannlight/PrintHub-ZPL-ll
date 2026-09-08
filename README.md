# PrintHub

PrintHub owns templates, rendering, logical print jobs, the public printer
catalog and IPP shares. Physical transports and vendor-specific configuration
belong to independent print services such as ZebraTamer. A future Niimbot
service can implement the same v2 contract while accepting raster pages only.

PrintHub has no required Thingdex, external database or hardware dependency.

## Run locally

From the product repository root, use `docker compose up -d`. For direct
development of this component:

```bash
python -m venv .venv
.venv/bin/pip install poetry
.venv/bin/poetry install
.venv/bin/poetry run uvicorn zplgrid.api:app --host 0.0.0.0 --port 8000
```

The OpenAPI document is available at `/openapi.json`; the checked-in artifact
is regenerated with `python scripts/export_openapi.py`.

## Print-service boundary

Connections are stored in the PrintHub data directory. The initial local
service is configured with:

- `PRINTHUB_PRINT_SERVICE_URL`
- `PRINTHUB_PRINT_SERVICE_TOKEN` or `PRINTHUB_PRINT_SERVICE_TOKEN_FILE`
- optional `PRINTHUB_PRINT_SERVICE_ID` to pin the expected stable identity

Additional first-start seeds can be supplied as JSON in
`PRINTHUB_ADDITIONAL_PRINT_SERVICES`. Runtime administration uses
`/v1/printer-services` and requires the PrintHub admin bearer token. Tokens are
stored separately from the public printer projection and are never returned by
the API.

The versioned wire contract, schemas and examples are in
[`docs/PRINT_SERVICE_PROTOCOL_V2.md`](docs/PRINT_SERVICE_PROTOCOL_V2.md) and
[`contracts/print-service-v2`](contracts/print-service-v2). Public printer IDs
combine a stable service connection with its local printer ID, so two services
may both expose a printer called `default` without collision.

## Job behavior

- `POST /v1/print-jobs` prepares a stored template.
- `POST /v1/print-jobs/raster` accepts an already prepared raster page.
- `POST /v1/print-jobs/documents` accepts PDF, PostScript, PNG, JPEG, PWG Raster
  and Apple Raster input.
- `GET /v1/print-jobs/{id}` reports the logical and downstream states.
- `POST /v1/print-jobs/{id}/retry` is allowed only for proven failures.
- `POST /v1/print-jobs/{id}/reprint` creates a deliberate new logical job from
  the immutable stored artifact and requires the admin token.

An idempotency key is bound to a canonical fingerprint of the request. Reusing
it for changed content returns HTTP 409. Resolved variables and exact delivery
artifacts are persisted before dispatch. A lost response therefore reuses the
same downstream idempotency key instead of creating another physical job.

Set `PRINTHUB_BACKGROUND_JOBS=1` in production. The durable worker resumes all
queued and service-waiting jobs after restart; recovery is not limited to the
UI history page. `transport_accepted` means all bytes reached the device
transport. It does not claim that a label was physically observed.

## Rendering and media safety

Native-ZPL printers receive ZPL. Raster-only printers receive the neutral
`application/vnd.printhub.raster-page+json` format after template rendering.
Labelary is opt-in with `ZPLGRID_ENABLE_LABELARY_API=1`; PDF and image input use
the local document raster pipeline and do not require Labelary.

The effective printer medium and DPI determine output dimensions. `hold`,
`fit`, and `fill` policies are explicit. A stale media revision, incompatible
page, or configured label-count limit is handled before device delivery.

## IPP

The separately built runtime image lives in [`ipp-gateway`](ipp-gateway). One
gateway process watches PrintHub's persistent `/v1/ipp-shares` registry and
manages zero or more stable queues on ports 8631–8650. It remains healthy with
no shares and refreshes queue capabilities after media changes.

The submission helper sends the original document with a durable IPP-derived
idempotency key and polls PrintHub briefly for holds, failures or a downstream
result. Long-running jobs remain safely owned by PrintHub's queue. A direct URI
is always available because Docker-hosted mDNS depends on the host network.

## Security

`PRINTHUB_ADMIN_TOKEN` or `PRINTHUB_ADMIN_TOKEN_FILE` protects service,
printer, media, IPP and explicit-reprint administration. Keep PrintHub bound to
loopback or behind an authenticated TLS reverse proxy. Do not place service
tokens in frontend configuration. Payloads, registry secrets and immutable job
artifacts belong in the persistent data volume and should be backed up together.

## Tests

```bash
poetry run pytest
python ipp-gateway/tests/test_gateway.py
python scripts/export_openapi.py
```

The raster-only conformance service in `simulators/raster-print-service` is a
test device, not a Niimbot driver. It can persist received PNG output and inject
offline, slow, lost-response and unknown-outcome behavior.
