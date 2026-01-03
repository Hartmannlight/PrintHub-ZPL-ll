# zplgrid (v1)

zplgrid compiles JSON layout templates into ZPL II. The repo also ships a small FastAPI
service that renders, previews, and prints labels, plus endpoints to store templates and
print drafts. This README is written for frontend developers who need enough context to
build a UI on top of the API.

## Project structure

- `zplgrid/`: core compiler and FastAPI app
- `zplgrid/schemas/`: JSON schemas (template v1, printers v1)
- `examples/`: sample template and compilation script
- `configs/`: printers.yml (runtime printer config)
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

- `split` node: divides a rectangle into two children.
  - `direction`: "v" (left/right) or "h" (top/bottom)
  - `ratio`: float between 0 and 1
  - `gutter_mm`: gap between children
  - `divider`: optional visible line inside the gutter
- `leaf` node: terminal region with exactly one element in v1.
  - `padding_mm`: [top, right, bottom, left] in mm
  - `debug_border`: draw a border when debugging

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

- `POST /v1/printers/{printer_id}/prints/zpl`
  - Body: `{ "zpl": "^XA...", "return_preview": false }`
- `POST /v1/printers/{printer_id}/prints/template`
  - Body: `{ "template": {...}, "variables": {...}, "debug": false, "target": {...}, "return_preview": false }`
  - If `target` is omitted, the printer's loaded media size and alignment are used.
- `GET /v1/printers` -> full config
- `GET /v1/printers/{printer_id}`
- `PUT /v1/printers/{printer_id}` -> upsert config
- `GET /v1/printers/{printer_id}/status` -> raw + parsed + normalized status JSON

Status response highlights:

- `raw`: raw text responses from `~HS`, `~HD`, `~HI`, `~HQES`
- `parsed`: legacy parsing (lists and key/value maps)
- `normalized.summary`: model/firmware/dpmm/memory plus `errors` and `warnings`

`return_preview` requires `ZPLGRID_ENABLE_LABELARY_PREVIEW=1` and returns
`preview_png_base64` in the response.

Printers are configured in `configs/printers.yml` (schema:
`zplgrid/schemas/printers_v1.schema.json`).

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
