# zplgrid / PrintHub (v1)

PrintHub is an independent template, render and print service. It does not
require Thingdex. Its primary web client is PrintHub Studio.

When an external PrinterFleet is configured, set either
`PRINTHUB_FLEET_API_TOKEN` or, preferably in production,
`PRINTHUB_FLEET_API_TOKEN_FILE` to a mounted service credential. Configuring
both fails startup. The HTTP adapter attaches that bearer credential and an
`X-Correlation-ID` to every catalog and delivery request. Its Fleet principal
needs only `observer` and `submitter` for the sites it serves.

Thingdex integration uses a durable PrintHub event outbox. Configure
`PRINTHUB_THINGDEX_EVENT_URL` and `PRINTHUB_THINGDEX_EVENT_SECRET` together;
partial configuration fails startup. Jobs submitted with `origin=thingdex` and
an `origin_reference` UUID enqueue signed, monotonically sequenced status
events. Delivery retries happen outside the print request and survive restarts.

## PrinterFleet boundary

Direct Ethernet/WLAN Zebra printers, serial-over-TCP bridges and PrintAgent
devices are registered and administered in PrinterFleet. Fleet Console is the
operator UI for discovery, status, queues, maintenance and auditing. PrintHub
receives only capability snapshots and submits immutable artifacts through its
narrow Fleet service credential.

`GET /v1/printers` and `GET /v1/printers/{id}` remain read-only PrintHub
conveniences for selecting a logical destination and its current media target.
PrintHub intentionally exposes no printer mutation, discovery, status-command,
registry import/export or raw-ZPL endpoint. Hardware integrations must use the
PrinterFleet API instead.

The local SQLite printer registry and background discovery remain available only
inside the compact legacy adapter as a rollback/migration baseline. They are not
part of the public PrintHub HTTP contract. New deployments configure
`PRINTHUB_FLEET_API_URL` and use PrinterFleet as the sole hardware authority.

## Typed template inputs

Entries in a template's `variables` array may include `label`, `type`,
`placeholder`, `options` and `source_hint` in addition to `name`, `mode` and
`default`. PrintHub Studio uses those fields to build the mobile form.
`source_hint` is optional integration metadata; standalone PrintHub users can
always enter the value manually.

zplgrid compiles JSON layout templates into ZPL II. The repo also ships a small FastAPI
service that renders, previews, and prints labels, plus endpoints to store templates and
print drafts. This README is written for frontend developers who need enough context to
build a UI on top of the API.

## Project structure

- `zplgrid/`: core compiler and FastAPI app
- `zplgrid/schemas/`: JSON schemas (template v1, printers v1)
- `examples/`: sample template and compilation script
- `configs/`: printers.yml (one-time printer seed), local registry default
- `templates/` and `drafts/`: persisted templates and drafts (created at runtime)

## Quick start

```bash
python examples/compile_example.py
```

This writes `examples/out.zpl`.

Start the API:

```bash
poetry run uvicorn zplgrid.api:app --reload
```

Base URL: `http://127.0.0.1:8000`

## Mental model for the frontend

### 1) Template JSON is a layout tree, not ZPL

- The template defines relative geometry; ZPL is produced later.
- All physical sizes are in millimeters.
- Layout uses a binary split tree.

### 2) Nodes

Every node may define an optional `background` image. Ancestor backgrounds are rendered first,
followed by descendant backgrounds and the leaf foreground elements.

- `split` node: divides a rectangle into two children.
  - `direction`: "v" (left/right) or "h" (top/bottom)
  - `ratio`: float between 0 and 1
  - `gutter_mm`: gap between children
  - `divider`: optional visible line inside the gutter
- `leaf` node: terminal region with exactly one element in v1.
  - `padding_mm`: [top, right, bottom, left] in mm
  - `debug_border`: draw a border when debugging
- `background` accepts the image fields `source`, `fit`, `align_h`, `align_v`,
  `input_dpi`, `threshold`, `dither`, and `invert` on split and leaf nodes, including root.

Canonical IDs (important for UI state):

- Root is `r`.
- Children are `r/0` and `r/1`, then `r/0/1`, etc.
- IDs are derived from structure only; changing ratio does not change IDs.

Optional aliases:

- `alias` is a unique human-friendly name for a node.
- Aliases are not used for identity.

### 3) Elements (one per leaf)

Common optional fields: `id`, `padding_mm`, `min_size_mm`, `max_size_mm`, `extensions`.

- `text`:
  - `text` supports `{placeholders}` and `\n`
  - `font_height_mm`, `font_width_mm`
  - `wrap`: none|word|char
  - `fit`: overflow|wrap|shrink_to_fit|truncate
  - `max_lines`, `align_h`, `align_v`
- `qr`:
  - `data` (supports placeholders)
  - `magnification` (1..10), `size_mode` fixed|max
  - `error_correction` L|M|Q|H
  - `input_mode` A|M, `character_mode` required if input_mode is M
  - `quiet_zone_mm`
  - `render_mode`: zpl|image
  - `theme` for image mode (preset/module_shape/finder_shape)
- `datamatrix`:
  - `data`, `module_size_mm`, `size_mode`
  - `columns` and `rows` required for size_mode "max"
  - `quiet_zone_mm`
  - `render_mode`: zpl|image
- `line`:
  - `orientation`: h|v
  - `thickness_mm`
  - `align`: start|center|end
- `image`:
  - `source.kind`: base64|url
  - `source.data`: raw base64 or URL (placeholders allowed)
  - `fit`: none|contain|cover|stretch
  - `align_h`, `align_v`, `input_dpi`, `threshold`, `dither`, `invert`
  - URL sources require env `ZPLGRID_ENABLE_IMAGE_URL=1`.

### 4) Defaults

Top-level `defaults` reduce repetition:

- `defaults.leaf_padding_mm`
- `defaults.text` (same fields as text element)
- `defaults.code2d` (quiet_zone_mm, size_mode, align_h, align_v, render_mode)
- `defaults.image` (fit, align, input_dpi, threshold, dither, invert)
- `defaults.render`:
  - `missing_variables`: error|empty
  - `emit_ci28`: enable UTF-8 in ZPL
  - `debug_padding_guides`, `debug_gutter_guides`

### 5) Variables and macros

Placeholders use Python format syntax: `{name}`.

- Escape literals with `{{` and `}}`.
- API requests currently fail if any placeholder is missing, even if
  `missing_variables` is "empty". Send all values or use macros.

Built-in macros (only added if missing from `variables`):

- `_now_iso`, `_date_yyyy_mm_dd`, `_date_dd_mm_yyyy`
- `_time_hh_mm`, `_time_hh_mm_ss`, `_timestamp_ms`
- `_uuid`, `_short_id`
- `_draft_id`, `_printer_id`, `_template_name`
- Counters (increment only when a template job is processed via `/v1/print-jobs`):
  - `_counter_global`, `_counter_daily`
  - `_counter_printer`, `_counter_printer_daily`
  - `_counter_template`, `_counter_template_daily`

Timezone for macros can be set via `ZPLGRID_TIMEZONE`.

### 6) Render target

Every render needs a target label size and DPI:

```json
{ "width_mm": 74.0, "height_mm": 26.0, "dpi": 203, "origin_x_mm": 0.0, "origin_y_mm": 0.0 }
```

### 7) Validation rules to enforce in UI

- `ratio` is 0 < ratio < 1.
- `gutter_mm` must be >= `divider.thickness_mm` when divider is visible.
- Exactly one element per leaf in v1.
- Text: `wrap` and `fit` must be compatible (see schema).
- DataMatrix size_mode "max" requires both `columns` and `rows`.
- QR input_mode "M" requires `character_mode`.

### 8) Known limitations (v1)

- No rotation support.
- No clipping of overflow.
- One element per leaf.
- DataMatrix auto-fit needs explicit columns and rows.
- Text sizing is heuristic in shrink_to_fit.

## API reference (frontend integration)

All endpoints are JSON over HTTP. Errors use standard FastAPI format:
`{ "detail": "..." }`.

### Render

- `POST /v1/renders/zpl` -> `{ "zpl": "^XA..." }`
- `POST /v1/renders/png` -> `image/png` (requires `ZPLGRID_ENABLE_LABELARY_API=1`)

Request body:

```json
{
  "template": { "...": "..." },
  "target": { "width_mm": 74.0, "height_mm": 26.0, "dpi": 203, "origin_x_mm": 0.0, "origin_y_mm": 0.0 },
  "variables": { "name": "Widget" },
  "debug": false
}
```

### Drafts (design -> operator handoff)

- `POST /v1/drafts` -> `{ "draft_id": "...", "expires_at": "..." }`
- `GET /v1/drafts/{draft_id}` -> full draft payload

Drafts expire after `ZPLGRID_PRINT_DRAFT_TTL_MINUTES` (default 30). Storage dir:
`drafts/` or `ZPLGRID_PRINT_DRAFTS_DIR`.

### Templates library

- `POST /v1/templates` -> saved template with id
- `PUT /v1/templates/{template_id}` -> update
- `GET /v1/templates` -> list
- `GET /v1/templates/{template_id}` -> detail
- `GET /v1/templates/{template_id}/preview` -> `image/png` (only if preview exists)

`POST /v1/templates` body:

```json
{
  "name": "my_template",
  "tags": ["shipping", "small"],
  "variables": [{ "name": "asset_id", "label": "Asset ID" }],
  "template": { "...": "..." },
  "sample_data": { "asset_id": "ABC-123" },
  "preview_target": { "width_mm": 50, "height_mm": 24, "dpi": 203, "origin_x_mm": 0, "origin_y_mm": 0 }
}
```

Previews are generated only if `ZPLGRID_ENABLE_LABELARY_TEMPLATES=1`.

Templates are stored under `templates/` (override with `ZPLGRID_TEMPLATES_DIR`).

### Printing

For saved templates, prefer the persistent job API:

- `POST /v1/print-jobs` creates a job before rendering and dispatch.
- `GET /v1/print-jobs` lists recent jobs.
- `GET /v1/print-jobs/{job_id}` returns its status and downstream job ID.
- `POST /v1/print-jobs/{job_id}/retry` explicitly retries a failed job.
- `POST /v1/print-jobs/raster` accepts physical-size-aware PNG, JPEG or PGM
  pages and creates the same durable job before any hardware I/O.
- `POST /v1/print-jobs/{job_id}/release` releases a held raster job with an
  explicit `fit` or `fill` scaling decision.

Raster jobs default to `scaling: "hold"`. If a page does not match the loaded
label, PrintHub stores the source and an exact one-bit print preview but sends
nothing to the device. `fit` preserves all content with margins; `fill` crops
centrally without distorting the aspect ratio. Each page is one label. Color
documents are converted through the common grayscale/dithering pipeline.
PrintHub submits the resulting versioned one-bit raster artifact to
PrinterFleet; it does not select a physical transport or create a device
payload. PrinterFleet's current Zebra driver produces ZPL `^GF`. A future
Niimbot driver can consume the same prepared artifact without changing IPP
ingestion, scaling, previews or persistent job handling.

`PRINTHUB_FLEET_API_URL` is required for printer catalog and delivery
operations. PrintHub deliberately has no local physical-printer registry or
transport fallback. A missing or unavailable Fleet is reported as HTTP 503;
template editing, rendering and already persisted logical jobs remain intact.

Jobs are stored under `ZPLGRID_PRINT_JOBS_DIR` (default
`/data/print-jobs`). An optional `idempotency_key` prevents duplicate printing
when a caller retries the same business event.

- `POST /v1/print-jobs`
  - Body: `{ "printer_id": "...", "template_id": "...", "variables": {...} }`
    or an immutable inline `"template": {...}` snapshot instead of `template_id`.
  - If `target` is omitted, the printer's loaded media size and alignment are used.
- `GET /v1/printers` -> full config
- `GET /v1/printers/{printer_id}`

### Common error cases

- 400: template validation or render error
- 403: Labelary endpoints disabled
- 404: missing template, draft, or printer
- 502: downstream Fleet or Labelary request failed
- 503: PrinterFleet is not configured or currently unavailable

## Example template (minimal)

```json
{
  "schema_version": 1,
  "name": "qr_left_text_right",
  "defaults": {
    "leaf_padding_mm": [1.5, 1.5, 1.5, 1.5],
    "text": {
      "font_height_mm": 4.0,
      "wrap": "word",
      "fit": "shrink_to_fit",
      "max_lines": 6,
      "align_h": "left",
      "align_v": "top"
    },
    "code2d": {
      "quiet_zone_mm": 1.0
    },
    "render": {
      "missing_variables": "error",
      "emit_ci28": true
    }
  },
  "layout": {
    "kind": "split",
    "direction": "v",
    "ratio": 0.3,
    "gutter_mm": 1.0,
    "divider": { "visible": true, "thickness_mm": 0.3 },
    "children": [
      {
        "kind": "leaf",
        "alias": "code",
        "elements": [
          { "type": "qr", "data": "{asset_id}", "magnification": 3 }
        ]
      },
      {
        "kind": "leaf",
        "alias": "text",
        "elements": [
          { "type": "text", "text": "{title}\\n{subtitle}", "align_v": "center" }
        ]
      }
    ]
  }
}
```

## Frontend checklist

- Build a tree editor with split + leaf nodes and show canonical IDs.
- Enforce schema constraints and invariants before sending to API.
- Provide variable extraction from `{placeholders}` and a data entry form.
- Use `/v1/renders/png` or `/v1/templates/.../preview` for previews (if enabled).
- For operator UI, submit saved templates or draft snapshots through `/v1/print-jobs`.

## Device and media ownership

Configure printers, loaded rolls, transport endpoints and PrintAgent devices in
PrinterFleet. PrintHub consumes that authoritative snapshot. If Fleet has no
media, no known DPI or is unavailable, automatic layout selection stops with a
clear error instead of guessing from stale configuration. Studio links to the
separately deployed Fleet Console for administration.

PrintHub does not inject darkness, speed or output mode into agent jobs. For
compiler-generated jobs it also omits the generated `^PW`/`^LL` header and does
not bake legacy registry calibration into layout coordinates. Device-specific
transport and maintenance policy remains behind PrinterFleet's driver boundary.


## Automated maintenance and releases

Push to main, exact vMAJOR.MINOR.PATCH tags, manual main runs and Monday 03:23 UTC clean rebuilds validate both native linux/amd64 and linux/arm64 candidates. Only the tested image archives are published. Platform SBOM and provenance attestations precede promotion of the index. Immutable sha-SHA-rRUN-ATTEMPT tags are never overwritten; latest moves only for the current main commit. Version tags do not move latest. No stable or major/minor aliases are promised while the release train is 0.x.

See [policy](docs/SECURITY_RELEASE_POLICY.md), [required owner setup](docs/MANUAL_GITHUB_SETUP.md) and [rollback](docs/ROLLBACK.md).
Renovate auto-merge remains blocked until protected-branch checks are verified. No deployment automation is installed.
