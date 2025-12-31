# zplgrid (v1)

`zplgrid` compiles a layout tree (split panes with relative ratios) into ZPL II for arbitrary label sizes.

Design goals:
- The template defines structure and relative geometry, not printer dots.
- Padding / thickness / gutters are always expressed in **mm**.
- Stable node identity: paths like `r/0/1/0` (ratio changes do not change identity).

## What v1 supports

- Split nodes: vertical (`v`) and horizontal (`h`) with `ratio` + `gutter_mm` and an optional visible divider line.
- Leaf nodes: exactly **one** element per leaf.
- Elements:
  - `text` (with wrap via `^FB`, and optional `shrink_to_fit` heuristic)
  - `qr` (ZPL `^BQN`)
  - `datamatrix` (ZPL `^BX`)
  - `line` (drawn via `^GB`)
- Debug borders for leaves and split dividers.

## Files

- `schemas/zplgrid_template_v1.schema.json`: JSON Schema (draft 2020-12).
- `zplgrid/`: library code.
- `examples/`: example template + compilation script.

## Quick start

```bash
python examples/compile_example.py
```

The example writes `out.zpl`.

## API: Render ZPL via HTTP

This repository includes a small FastAPI service that renders ZPL II from a template JSON payload.

### Run the server

```bash
poetry run uvicorn zplgrid.api:app --reload
```

The API listens at `http://127.0.0.1:8000` by default.

### Endpoint

`POST /v1/render/zpl`

Request body:

```json
{
  "template": { "...": "..." },
  "target": { "width_mm": 74.0, "height_mm": 26.0, "dpi": 203, "origin_x_mm": 0.0, "origin_y_mm": 0.0 },
  "variables": { "name": "Widget" },
  "debug": false
}
```

Response:

```json
{
  "zpl": "^XA..."
}
```

### Errors

- Missing variables or invalid templates return `400` with a short `detail` message.

## Important limitations (by design in v1)

- No rotations.
- No clipping (ZPL does not clip fields like CSS).
- Text sizing is heuristic unless you add a better `TextMeasurer` later.
- QR auto-fit is optional; DataMatrix auto-fit requires explicit `columns` and `rows`.
















# zplgrid v1 — Project Handover Spec (for the Web Template Builder (other project work in progress))

This document describes the **template JSON format**, **design decisions**, **validation rules**, and the **mental model** needed to build a web UI that outputs correct JSON for the `zplgrid` compiler. The website’s only job is to produce valid JSON templates; the Python library will validate and compile the template into ZPL II.

---

## 1) High-level purpose

**Problem:** ZPL II is “absolute” (printer dots). The goal is to define templates that work across **many label sizes** without rewriting per format.

**Solution:** A template is not “ZPL with placeholders”, but a **recursive split layout tree** (like split panes).

* The tree is defined in **relative geometry** (ratios).
* Physical values (padding, line thickness, gutter, module size, etc.) are always in **millimeters**.
* At compile time, the library converts everything to printer dots using the chosen label size and DPI, resolves the layout, then emits ZPL.

---

## 2) Core layout model

### 2.1 Node types

The `layout` field is a tree of nodes. Each node is either:

* **split node**: divides a region into two child regions.
* **leaf node**: terminal region containing exactly **one element** in v1.

### 2.2 Deterministic node identity (critical for the UI)

The compiler uses **canonical node IDs** based on the path in the tree:

* Root node ID is always: `r`
* A split node has exactly 2 children, indexed:

  * child 0 → node ID path suffix `/0`
  * child 1 → node ID path suffix `/1`

Examples:

* Left child of root: `r/0`
* Right child of root: `r/1`
* Right child’s top child: `r/1/0`

**Important:** These IDs are **not stored in JSON**; they are derived from the structure.

**Design requirement met:** If you only change a split’s `ratio`, `gutter_mm`, or divider settings, the structure doesn’t change ⇒ the canonical IDs stay the same.

**When IDs change:** If you insert/remove nodes (structure change), paths shift. That is considered a “new template” and it’s acceptable.

### 2.3 Aliases (human-friendly names)

Nodes may include an optional `alias` string.

* Alias must be unique across the entire tree.
* Alias is purely for UI convenience (display/select), not identity.
* Your website can let users label regions like `"left"`, `"code"`, `"text_top"`, etc.

---

## 3) Split semantics (how geometry is computed)

Split nodes define how to carve a parent rectangle into two child rectangles.

### 3.1 Split direction

* `direction: "v"` → vertical split (left/right)
* `direction: "h"` → horizontal split (top/bottom)

### 3.2 Split ratio

* `ratio` is a float `0 < ratio < 1`
* For `"v"`: child0 is left width = `ratio`, child1 is remainder
* For `"h"`: child0 is top height = `ratio`, child1 is remainder

### 3.3 Gutter and divider

A split can have:

* `gutter_mm`: spacing between child0 and child1 (mm)
* `divider`: optional visible line with `thickness_mm` (mm)

**Hard invariant (enforced by validation):**

* If `divider.visible == true`, then `gutter_mm >= divider.thickness_mm`

**Meaning:** The divider line is drawn **inside the gutter** (not over content). This avoids “divider cuts the QR/text” bugs.

### 3.4 Deterministic rounding in dots

At compile time, mm → dots yields integers. When splitting:

* available = parent_length_dots − gutter_dots
* child0 = floor(available * ratio)
* child1 = available − child0

This guarantees:

* no missing pixels
* `child0 + gutter + child1 == parent` always

---

## 4) Leaf semantics

A leaf node is a rectangle that can contain content.

### 4.1 Leaf padding

Leaf nodes may have:

* `padding_mm: [top, right, bottom, left]` (all ≥ 0)

If missing, leaf padding comes from top-level `defaults.leaf_padding_mm`.

**After padding**, the remaining rectangle is the **content rect**. The element is placed into that.

### 4.2 Exactly one element per leaf (v1)

The JSON field is `elements: [ ... ]`, but validation requires:

* `elements` must contain **exactly 1** element.

**UI implication:** If the user wants multiple items in one area, they must create additional splits.

---

## 5) Elements (v1)

### Common element fields (shared across all types)

Elements may include:

* `id: string` (optional)

  * purely for diagnostics (helpful for UI)
* `padding_mm: [t,r,b,l]` (optional, mm)

  * padding inside the leaf content rect
* `min_size_mm: [w,h]` (optional, mm)

  * if the computed box is smaller ⇒ compilation error
* `max_size_mm: [w,h]` (optional, mm)

  * if bigger ⇒ element box is reduced and centered
* `extensions: object` (optional)

  * arbitrary UI metadata (ignored by compiler)

**Sizing rule (v1):**

* element default box = “fill leaf content rect”
* apply element padding
* enforce min/max size if present (max shrinks and centers)

### 5.1 Text element (`type: "text"`)

Required:

* `text: string`

Optional settings:

* `font_height_mm: number > 0`
* `font_width_mm: number > 0` (defaults to `font_height_mm` if absent)
* `wrap: "none" | "word" | "char"`
* `fit: "overflow" | "wrap" | "shrink_to_fit" | "truncate"`
* `max_lines: int >= 1`
* `align_h: "left" | "center" | "right"`
* `align_v: "top" | "center" | "bottom"`

Defaults can be specified globally via `defaults.text` (details below).

**Newlines in text:**

* The compiler supports:

  * actual newline characters
  * literal `\n` sequences (two characters backslash+n)
* The compiler converts them to ZPL newline control (`\&`) internally.

**Important (ZPL reality):**

* ZPL doesn’t “clip” like HTML. If you choose `fit="overflow"`, content may exceed the leaf.
* `wrap` and `max_lines` are implemented via `^FB` in ZPL.
* `shrink_to_fit` uses a **heuristic** text measurer (replaceable later). It repeatedly reduces font size until the estimated content fits (or hits 1 dot).

**UI recommendation:**

* Offer fit modes as an explicit dropdown.
* If `align_v` is center/bottom, explain that vertical placement depends on estimated text height.

### 5.2 QR element (`type: "qr"`)

Required:

* `data: string`

Optional:

* `magnification: int 1..10` (optional; if omitted compiler chooses a DPI-based default)
* `size_mode: "fixed" | "max"` (default "fixed")
* `align_h: "left" | "center" | "right"` (default "center")
* `align_v: "top" | "center" | "bottom"` (default "center")
* `error_correction: "L" | "M" | "Q" | "H"` (default "M")
* `input_mode: "A" | "M"` (default "A")
* `character_mode`: required for `input_mode="M"` ("N" numeric or "A" alphanumeric)
* `quiet_zone_mm: number >= 0` (optional; can come from `defaults.code2d.quiet_zone_mm`)

Note: QR model is fixed to 2 in this project.

**Sizing behavior (v1):**

* The element box is made square based on `min(w,h)` after quiet zone.
* The QR is centered in the available inner square.
* If `size_mode="max"`, the compiler picks the largest magnification that fits inside the inner square.

**UI recommendation:**

* Always expose `quiet_zone_mm` (or apply a sensible global default).
* Provide magnification either:

  * “Auto” (omit the field), or
  * explicit numeric selection.

### 5.3 DataMatrix element (`type: "datamatrix"`)

Required:

* `data: string`

Optional:

* `module_size_mm: number > 0` (default 0.5mm in compiler)
* `size_mode: "fixed" | "max"` (default "fixed")
* `align_h: "left" | "center" | "right"` (default "center")
* `align_v: "top" | "center" | "bottom"` (default "center")
* `quality: 200` (default 200; ECC200 only)
* `columns: int 0..49` (default 0 = auto)
* `rows: int 0..49` (default 0 = auto)
* `format_id: int 0..6` (default 6)
* `escape_char: single character string` (default "_")
* `quiet_zone_mm: number >= 0` (optional; can come from `defaults.code2d.quiet_zone_mm`)

**UI recommendation:**

* Most users should only set `module_size_mm` + `quiet_zone_mm`.
* Keep the advanced parameters behind an “advanced” toggle.

### 5.4 Line element (`type: "line"`)

Required:

* `orientation: "h" | "v"`
* `thickness_mm: number > 0`

Optional:

* `align: "start" | "center" | "end"` (default center)

**Meaning:**

* Horizontal line: spans the element’s width, thickness is the line’s height.
* Vertical line: spans the element’s height, thickness is the line’s width.

---

## 6) Global defaults (top-level `defaults`)

Top-level `defaults` allows the template to define common behavior so the UI doesn’t have to repeat settings everywhere.

### 6.1 `defaults.leaf_padding_mm`

Applies to any leaf that does not specify its own `padding_mm`.

### 6.2 `defaults.text`

These values are merged into each text element (element fields override defaults):

* `font_height_mm`
* `font_width_mm`
* `wrap`
* `fit`
* `max_lines`
* `align_h`
* `align_v`

### 6.3 `defaults.code2d`

Merged into both QR and DataMatrix elements:

* `quiet_zone_mm`
* `size_mode`
* `align_h`
* `align_v`

### 6.4 `defaults.render`

Controls rendering/encoding behaviors:

* `missing_variables: "error" | "empty"`

  * `"error"`: compilation fails if a `{placeholder}` is missing
  * `"empty"`: missing placeholders become empty strings
* `emit_ci28: boolean`

  * If true, the compiler emits `^CI28` to enable UTF-8 text handling in ZPL output.
  * Recommended if you expect umlauts or non-ASCII.

**UI recommendation:**

* Expose these in a “Template Settings” panel.
* Default should be:

  * `missing_variables = "error"`
  * `emit_ci28 = true`

---

## 7) Placeholders / variable binding

Text and code data support Python-style format placeholders:

* Example: `"data": "{asset_id}"`
* Example: `"text": "Name: {name}\nID: {asset_id}"`

At compile time, the library does `str.format_map(variables)`.

**Rules for the UI:**

* Placeholders are delimited by `{...}`.
* If the user needs literal `{` or `}`, they must be escaped as `{{` and `}}` (Python format rules).
* Missing variables behavior is controlled by `defaults.render.missing_variables`.

**Editor UX suggestion:**

* Provide a “Variables used in this template” view by parsing `{identifier}` occurrences.
* Provide validation warnings if placeholders look malformed.

---

## 8) JSON Schema and validation rules

### 8.1 Schema location

The schema shipped with the project:

* `schemas/zplgrid_template_v1.schema.json` (copy)
* `zplgrid/schemas/zplgrid_template_v1.schema.json` (used by Python validation)

The Python library validates with `jsonschema` (Draft 2020-12) and then runs extra checks.

### 8.2 Additional invariants enforced by the Python lib

Even if the JSON “looks ok”, compilation can fail if:

* divider is visible but `gutter_mm < thickness_mm`
* leaf `elements` is not exactly length 1 (v1)
* `min_size_mm` doesn’t fit the computed element box

**UI implication:** you should proactively prevent these states, not just rely on backend errors.

---

## 9) Versioning strategy (future-proofing)

* The JSON has `schema_version: 1`.
* For breaking changes (multiple elements per leaf, rotations, additional placement modes, etc.), introduce `schema_version: 2`, keep v1 parser for compatibility.

**UI should:**

* always emit `schema_version: 1` for now
* keep unknown extra app fields inside `extensions` objects so old compilers ignore them safely

---

## 10) Explicitly out-of-scope in v1 (so the UI must not promise it)

* No rotation support.
* No "true clipping" of overflow.
* DataMatrix auto-fit requires explicit `columns` and `rows` to compute the module size.
* No multi-element leaf layout/flow (stacking). Use splits instead.

---

## 11) Recommended UI structure (practical guidance)

### 11.1 Editor model

Represent the template as:

* a tree view (nodes)
* plus a visual preview grid (optional, not required to be accurate in dots)

Each node:

* shows canonical node ID (computed), e.g. `r/1/0`
* shows optional alias
* shows node type: split or leaf

### 11.2 Split node UI

Controls:

* direction toggle (vertical/horizontal)
* ratio slider (0.01 … 0.99)
* gutter_mm numeric input (≥ 0)
* divider toggle
* divider thickness_mm input (only enabled if divider visible)
  Validation hints:
* enforce `gutter_mm >= divider.thickness_mm` when divider visible

### 11.3 Leaf node UI

Controls:

* padding_mm editor (4 numeric mm inputs)
* debug_border toggle (optional)
* element editor (exactly one element in v1)
* optional alias

### 11.4 Element editors

Provide a type switch:

* Text / QR / DataMatrix / Line

For each element:

* show optional element id (string)
* show padding_mm
* show min_size_mm / max_size_mm with warnings

Text element controls:

* text editor with placeholder help
* wrap mode
* fit mode
* max lines
* alignment (H/V)
* font size in mm (height, optionally width)

QR controls:

* data template
* ECC
* magnification (Auto or 1..10)
* size_mode ("fixed" or "max")
* align_h / align_v
* quiet zone mm (or inherit from defaults)

DataMatrix controls:

* data template
* module_size_mm
* size_mode ("fixed" or "max")
* align_h / align_v
* quiet zone mm
* advanced: quality, columns/rows, format id

Line controls:

* orientation
* thickness_mm
* align start/center/end

### 11.5 Defaults panel

* leaf padding default
* text defaults
* code2d defaults
* render defaults

---

## 12) Minimal example template (what the UI should produce)

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

---

## 13) What the website does NOT need to handle

* DPI conversions or printer dots
* ZPL command syntax
* ZPL escaping rules
* Layout rounding rules
* Any compilation logic

It only needs to:

* build valid JSON according to the schema
* enforce the extra invariants early (divider/gutter, 1 element per leaf, etc.)
* optionally provide a preview (can be approximate)

---

If you want, I can also provide:

* a “UI-oriented” JSON schema subset (with descriptions/tooltips for each field), or
* a typed TypeScript model that mirrors the schema (for React/Vue form generation).
