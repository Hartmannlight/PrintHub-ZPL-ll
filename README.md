# zplgrid / PrintHub (v1)

PrintHub is an independent template, render and print service. It does not
require Thingdex. Its primary web client is PrintHub Studio.

When an external PrinterFleet is configured, set
`PRINTHUB_FLEET_API_TOKEN` to its service credential. The HTTP adapter attaches
that bearer credential and an `X-Correlation-ID` to every catalog and delivery
request.

Thingdex integration uses a durable PrintHub event outbox. Configure
`PRINTHUB_THINGDEX_EVENT_URL` and `PRINTHUB_THINGDEX_EVENT_SECRET` together;
partial configuration fails startup. Jobs submitted with `origin=thingdex` and
an `origin_reference` UUID enqueue signed, monotonically sequenced status
events. Delivery retries happen outside the print request and survive restarts.

## ZebraTamer printers

ZebraTamer is the preferred hardware boundary. Register a printer with:

```yaml
connection:
  protocol: zebra_tamer
  base_url: http://zpl-agent.local:8080
  printer_id: schildkrote
  timeout_ms: 10000
```

PrintHub submits `application/zpl` to
`POST /v1/printers/{printer_id}/jobs` and returns the ZebraTamer job id/state to
the client. Printer status comes from the ZebraTamer snapshot API.

`GET /v1/zebra-tamer/agents` performs best-effort mDNS discovery. Explicit
fallback URLs can be supplied as a comma-separated list in
`ZPLGRID_ZEBRA_TAMER_AGENTS`.

Legacy `raw9100` connections remain supported for migration and emulators.

### Persistent printer registry

`ZPLGRID_PRINTER_REGISTRY_PATH` selects the SQLite inventory (default
`configs/printers.sqlite3`; use `/data/printers.sqlite3` in containers). No separate
database server is required. `ZPLGRID_PRINTER_SEED_PATH` defaults to
`configs/printers.yml`. The seed is imported **once**, transactionally, preserving
public IDs and all settings. An immutable seed snapshot is kept inside SQLite.
The seed file is never written and should be mounted read-only. Subsequent seed
edits are ignored, including after restart. Back up the database and seed before
migration. Conflicting duplicate devices abort migration without changing YAML.

Discovery observes agents, not printer configuration. New printers must be
explicitly registered with `POST /v1/printers/register` after configuring media
and DPI in ZebraTamer. PrintHub reads those values from the agent; it does not
accept replacement defaults from the registration form. Repeat registration
preserves all settings. New public IDs are stable
`zt-<UUID>` values derived from agent identity and local printer ID; imported IDs
are never renamed. Agent URLs and device identity must not be used as UI keys.

Modern agents expose a persistent `agent_id`. Known devices can follow verified
address changes; a different agent at an old address is rejected. Legacy agents
without an ID remain address-bound and cannot safely follow arbitrary IP changes.
Upgrade them to enable stable identity. Aliases are deduplicated by agent ID.
Before sending a job to a stable-ID agent, its identity is verified again.

Background discovery runs every 30 seconds (`ZPLGRID_DISCOVERY_INTERVAL_SECONDS`,
`0` disables the background task). Manual refresh is `GET /v1/zebra-tamer/agents`;
`POST /v1/zebra-tamer/discover` with `{"base_url":"http://pi:8080"}` also checks a
manual address. Registered addresses and environment URLs remain fallback sources
when multicast fails. Unreachable printers stay in inventory with offline status.

`GET /v1/printers/{id}/configuration` returns stored settings for editing, while
the ordinary GET resolves authoritative ZebraTamer media or live emulator media.
Agent media, alignment and device values are not editable in PrintHub. Edit with
`PATCH /v1/printers/{id}` and `{"revision":1,"settings":{"name":"Workshop"}}`.
The revision comes from `registry.revision`. A stale revision or identity conflict
returns 409; PATCH cannot change ID or connection. Legacy PUT is create-or-identical
and rejects destructive replacement. Use settings PATCH instead.

`GET /v1/printer-registry/export` downloads YAML. POST that parsed configuration
as JSON to `/v1/printer-registry/import` for additive, all-or-nothing import.
Different existing entries and duplicate endpoints are rejected. Export contains
saved configuration only, not runtime metadata. Before rolling back to a pre-registry
version, export YAML; old versions cannot read SQLite. `ZPLGRID_PRINTER_OVERRIDES_PATH`
is obsolete and unused. `ZPLGRID_DEFAULT_PRINTER_ID` is returned in the printer list
when it names an enabled printer, otherwise the first enabled printer is selected.

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
- Counters (increment only on print via `/prints/template`):
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
documents are converted through the common grayscale/dithering pipeline before
the selected device driver encodes them.

The raster service is intentionally independent of ZPL. `RasterDriver` encodes
the prepared one-bit page and `PrinterBackend` transports the resulting device
artifact. The current adapters produce ZPL `^GF` and dispatch it over raw 9100
or ZebraTamer. Future bitmap devices can add their own driver/agent adapter
without changing IPP ingestion, scaling, previews or persistent job handling.

Jobs are stored under `ZPLGRID_PRINT_JOBS_DIR` (default
`/data/print-jobs`). An optional `idempotency_key` prevents duplicate printing
when a caller retries the same business event. The synchronous endpoints below
remain available for drafts and compatibility clients.

- `POST /v1/printers/{printer_id}/prints/zpl`
  - Body: `{ "zpl": "^XA...", "return_preview": false }`
- `POST /v1/printers/{printer_id}/prints/template`
  - Body: `{ "template": {...}, "variables": {...}, "debug": false, "target": {...}, "return_preview": false }`
  - If `target` is omitted, the printer's loaded media size and alignment are used.
- `GET /v1/printers` -> full config
- `GET /v1/printers/{printer_id}`
- `PUT /v1/printers/{printer_id}` -> create or return identical config; conflicts return 409
- `PATCH /v1/printers/{printer_id}` -> revision-checked settings update
- `GET /v1/printers/{printer_id}/status` -> raw + parsed + normalized status JSON

Status response highlights:

- `raw`: raw text responses from `~HS`, `~HD`, `~HI`, `~HQES`
- `parsed`: legacy parsing (lists and key/value maps)
- `normalized.summary`: model/firmware/dpmm/memory plus `errors` and `warnings`

`return_preview` requires `ZPLGRID_ENABLE_LABELARY_PREVIEW=1` and returns
`preview_png_base64` in the response.

Printers are stored in the SQLite registry. YAML import/export follows
`zplgrid/schemas/printers_v1.schema.json`.

### Common error cases

- 400: template validation or render error
- 403: Labelary endpoints disabled
- 404: missing template, draft, or printer
- 502: printer I/O or Labelary service failure

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
- For operator UI, use drafts or templates plus `/prints/template`.
## ZebraTamer device and media ownership

For `zebra_tamer` connections, configure the printer and loaded roll in
ZebraTamer's optional `/ui/` WebUI. PrintHub reads authoritative size, color and
resolution from `GET /v1/printers/{id}/configuration`; it does not maintain a
second editable media/device profile. If the agent has no media, no known DPI,
or is unavailable, automatic layout selection stops with a clear error instead
of using stale registry values. Explicit raw ZPL can still be sent independently.

Existing registry IDs, connections and original migrated configurations remain
intact. Old device/media fields are archival only for agent connections. Register
new agents after setting up their media and DPI in ZebraTamer. Registry edits for
agent media/alignment/ZPL are rejected; display name, enabled state and job
defaults remain editable here. The Studio links to ZebraTamer for administration.

PrintHub no longer injects darkness, speed, or output mode into agent jobs. For
compiler-generated jobs it also omits the generated `^PW`/`^LL` header and does not
bake the legacy registry calibration into layout coordinates. Caller-supplied raw
ZPL is not stripped: intentional device commands in it still take effect. Raw
TCP printers and the emulator retain their existing behavior.


## Automated maintenance and releases

Push to main, exact vMAJOR.MINOR.PATCH tags, manual main runs and Monday 03:23 UTC clean rebuilds validate both native linux/amd64 and linux/arm64 candidates. Only the tested image archives are published. Platform SBOM and provenance attestations precede promotion of the index. Immutable sha-SHA-rRUN-ATTEMPT tags are never overwritten; latest moves only for the current main commit. Version tags do not move latest. No stable or major/minor aliases are promised while the release train is 0.x.

See [policy](docs/SECURITY_RELEASE_POLICY.md), [required owner setup](docs/MANUAL_GITHUB_SETUP.md) and [rollback](docs/ROLLBACK.md).
Renovate auto-merge remains blocked until protected-branch checks are verified. No deployment automation is installed.
