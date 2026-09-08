# Print Service Protocol v2

Status: implementation contract for the standalone PrintHub architecture.

This protocol connects PrintHub to hardware-owning services such as
ZebraTamer. It deliberately contains no Zebra configuration fields. Vendor
features are advertised as optional extensions.

The normative JSON schemas live in `contracts/print-service-v2/`. HTTP JSON
responses use the document itself as the response body; errors use the common
error schema. All timestamps are RFC 3339 UTC values.

## Identity and authentication

`GET /v2/service` returns a persistent `service_id`, implementation name,
version and protocol version. The tuple `(service_id, printer_id)` is the stable
physical-printer identity. A service URL or IP address may change without
changing identity.

Every `/v2` endpoint except `/healthz` requires a bearer credential. Services
support at least `read`, `print` and `admin` permissions. A deployment may use
one credential with all permissions, but must not ship a universal default
secret. PrintHub stores service credentials outside public printer documents.

## Endpoints

| Method and path | Permission | Meaning |
| --- | --- | --- |
| `GET /healthz` | none | Process readiness; printer availability is not readiness |
| `GET /v2/service` | read | Stable service identity and protocol information |
| `GET /v2/printers` | read | Printer summaries; supports `cursor` and `limit` |
| `GET /v2/printers/{printer_id}` | read | Current printer capabilities, profile, media and observation |
| `POST /v2/printers/{printer_id}/jobs` | print | Atomically accept one complete immutable job |
| `GET /v2/jobs/{job_id}` | read | Read the durable service job |
| `GET /v2/jobs/by-idempotency/{key}` | read | Resolve a lost submission response |
| `GET /v2/jobs` | read | Paginated history; optional printer/state filters |
| `POST /v2/printers/{printer_id}/queue/pause` | admin | Pause work that has not begun hardware transfer |
| `POST /v2/printers/{printer_id}/queue/resume` | admin | Resume FIFO processing |
| `POST /v2/jobs/{job_id}/cancel` | admin | Cancel a job only while no hardware byte has been sent |
| `PUT /v2/admin/printers/{printer_id}/media` | admin | Replace loaded-media state when the service supports media management |

Optional endpoints are exposed only when their corresponding capability is
supported. ZebraTamer uses `POST /v2/extensions/zebra/printers/{printer_id}`
for its transport/device configuration and
`POST /v2/extensions/zebra/printers/{printer_id}/maintenance/{action}` for
allowlisted maintenance. Generic clients never send arbitrary vendor bytes
through an extension proxy. The former `/v2/admin/printers/...` Zebra routes
remain temporary aliases for clients from the refactoring window.

## Printer document

A printer exposes:

- local `printer_id` and display name;
- accepted MIME types;
- resolution and maximum raster bounds;
- media with a monotonically changing `revision`;
- queue state and current observation timestamp;
- capability states `supported`, `unsupported` or `unknown`.

Unknown or stale hardware information stays explicit. It is never converted to
`false`, zero or an empty collection solely to simplify a client model.

## Atomic job submission

The request follows `job-submit.schema.json`. It contains one or more ordered
artifacts. The service validates and durably stores the envelope, all artifact
bytes, their hashes, the idempotency record and queue position before returning
HTTP 202. A partially uploaded job is never visible as queued and is never sent
to hardware.

Each artifact uses exactly one of:

- `application/zpl`, where `data_base64` contains the complete native ZPL;
- `application/vnd.printhub.raster-page+json`, whose decoded JSON follows
  `raster-page-v1.schema.json`.

The `copies` value belongs to the job envelope and applies to the ordered
artifact list as collated sets: for artifacts A and B with two copies, output is
`A, B, A, B`. Raster page v1 retains its legacy `copies` member during
migration, but v2 requires it to be `1`; a mismatch is rejected. Native ZPL
submitted through v2 must not contain an effective `^PQ` greater than one when
envelope copies are greater than one. ZebraTamer rejects ambiguous duplication
rather than guessing.

The optional `media_revision` is the revision used by PrintHub while preparing
the job. If current media differs before the first hardware byte, the service
holds the job with reason `media_revision_changed`. It never rerenders.

## Idempotency

`idempotency_key` is unique within one service. The canonical request hash
covers service printer ID, ordered artifact MIME types and SHA-256 values,
copies, media revision and effective options.

- Reusing a key with the same canonical hash returns the original job.
- Reusing it with different content or options returns HTTP 409
  `idempotency_conflict`.
- A lost HTTP response is resolved by lookup or by resubmitting the identical
  request.
- Cleanup may delete large payloads, but must retain enough tombstone data to
  prevent an old key from silently becoming a new physical job.
- An explicit user reprint always receives a new key and records the original
  job as `reprint_of`.

## Raster page v1

Raster data is row-major, one bit per pixel and MSB-first. `1` means black and
`0` means white. Every row occupies `ceil(width_px / 8)` bytes. Unused low bits
in the last byte of each row must be zero. Payload length must exactly equal
`ceil(width_px / 8) * height_px`.

The service validates positive dimensions, declared DPI, decoded length,
padding and its printer profile before queueing. It performs device framing but
does not scale, rotate or dither the image.

## Job states

| State | Meaning |
| --- | --- |
| `queued` | Complete job is durable and awaiting its printer FIFO |
| `held` | Durable but blocked by queue pause, media/profile conflict or operator decision |
| `transmitting` | At least one hardware operation is active; output may have begun |
| `transport_accepted` | Transport accepted all requested bytes; paper output is not proven |
| `completed_observed` | Reliable device evidence or an explicitly identified operator confirmation exists |
| `failed` | No further automatic work is scheduled; per-artifact evidence explains what happened |
| `outcome_unknown` | Hardware may have received bytes; automatic physical retry is forbidden |
| `cancelled` | Cancelled before any hardware byte was sent |

Connection failures proven to occur before the first byte may move back to
`queued` with bounded retry metadata. Once any artifact can have reached the
device, the service records progress and never automatically starts the whole
job again. A temporarily unreachable status endpoint does not alter the last
durable physical outcome.

## Errors and limits

Errors follow `error.schema.json` and include a stable code, human-readable
message and optional field details. Implementations publish limits in the
service document and reject oversize jobs before persistence. Payloads,
credentials and raw device responses are not written to ordinary request logs.

## Compatibility

Additive response fields are allowed in v2. Clients ignore unknown fields.
Removing fields, changing state meanings, raster polarity/order, copy ordering
or idempotency behavior requires a new protocol version. ZebraTamer's legacy
`/v1` API is a migration interface and is not the v2 contract.
