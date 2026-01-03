from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from fastapi import FastAPI, HTTPException, Response
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from .exceptions import CompilationError, LayoutError, TemplateRenderError, TemplateValidationError
from .labelary import render_labelary_png_bytes
from .macros import MacroContext, build_macro_variables, collect_template_placeholders, now_for_macros
from .model import DataMatrixElement, LabelTarget, LeafNode, QrElement, SplitNode, Template, TextElement
from .parser import load_template
from .printer_io import apply_printer_settings, query_raw_command, send_raw_zpl
from .printers_config import load_printers_config, save_printers_config
from .print_drafts_store import load_print_draft, save_print_draft
from .render import RenderOptions, render_text
from .templates_store import load_template_entry, list_templates, save_template_entry, update_template_entry


class RenderTarget(BaseModel):
    width_mm: float = Field(..., gt=0)
    height_mm: float = Field(..., gt=0)
    dpi: int = Field(203, gt=0)
    origin_x_mm: float = Field(0.0, ge=0)
    origin_y_mm: float = Field(0.0, ge=0)


class RenderRequest(BaseModel):
    template: dict[str, Any]
    target: RenderTarget
    variables: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False


class RenderResponse(BaseModel):
    zpl: str


load_dotenv()

app = FastAPI(title="zplgrid API", version="1.0")


class PrintersConfigResponse(BaseModel):
    config_version: int
    printers: list[dict[str, Any]]


@app.on_event("startup")
def _load_printers_config_on_startup() -> None:
    try:
        app.state.printers_config = load_printers_config()
    except ValueError as exc:
        raise RuntimeError(f'Failed to load printers.yml: {exc}') from exc


def _assert_variables_present(template: Template, variables: Mapping[str, Any]) -> None:
    options = RenderOptions(missing_variables="error")

    def check_node(node) -> None:
        if isinstance(node, LeafNode):
            element = node.elements[0]
            if isinstance(element, TextElement):
                render_text(element.text, variables, options=options)
            elif isinstance(element, QrElement):
                render_text(element.data, variables, options=options)
            elif isinstance(element, DataMatrixElement):
                render_text(element.data, variables, options=options)
            return
        if isinstance(node, SplitNode):
            for child in node.children:
                check_node(child)

    check_node(template.layout)


def _labelary_api_enabled() -> bool:
    return os.getenv('ZPLGRID_ENABLE_LABELARY_API', '') == '1'


def _labelary_preview_enabled() -> bool:
    return os.getenv('ZPLGRID_ENABLE_LABELARY_PREVIEW', '') == '1'


def _labelary_templates_enabled() -> bool:
    return os.getenv('ZPLGRID_ENABLE_LABELARY_TEMPLATES', '') == '1'


def _target_to_labelary_args(target: RenderTarget) -> tuple[int, float, float]:
    dpmm = max(1, int(round(target.dpi / 25.4)))
    label_width_in = target.width_mm / 25.4
    label_height_in = target.height_mm / 25.4
    return dpmm, label_width_in, label_height_in


@app.post("/v1/renders/zpl", response_model=RenderResponse)
def render_zpl(payload: RenderRequest) -> RenderResponse:
    try:
        template = load_template(payload.template)
        used_names = collect_template_placeholders(template)
        macro_vars = build_macro_variables(
            used_names,
            existing_variables=payload.variables,
            context=MacroContext(
                template_name=str(payload.template.get('name')) if isinstance(payload.template, dict) else None,
                printer_id=None,
                draft_id=None,
                now=now_for_macros(),
                increment_counters=False,
            ),
        )
        variables = {**macro_vars, **payload.variables}
        _assert_variables_present(template, variables)
        target = LabelTarget(
            width_mm=payload.target.width_mm,
            height_mm=payload.target.height_mm,
            dpi=payload.target.dpi,
            origin_x_mm=payload.target.origin_x_mm,
            origin_y_mm=payload.target.origin_y_mm,
        )
        zpl = template.compile(target=target, variables=variables, debug=payload.debug)
        return RenderResponse(zpl=zpl)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/renders/png")
def render_png(payload: RenderRequest) -> Response:
    if not _labelary_api_enabled():
        raise HTTPException(status_code=403, detail='Labelary render API is disabled')
    try:
        template = load_template(payload.template)
        used_names = collect_template_placeholders(template)
        macro_vars = build_macro_variables(
            used_names,
            existing_variables=payload.variables,
            context=MacroContext(
                template_name=str(payload.template.get('name')) if isinstance(payload.template, dict) else None,
                printer_id=None,
                draft_id=None,
                now=now_for_macros(),
                increment_counters=False,
            ),
        )
        variables = {**macro_vars, **payload.variables}
        _assert_variables_present(template, variables)
        target = LabelTarget(
            width_mm=payload.target.width_mm,
            height_mm=payload.target.height_mm,
            dpi=payload.target.dpi,
            origin_x_mm=payload.target.origin_x_mm,
            origin_y_mm=payload.target.origin_y_mm,
        )
        zpl = template.compile(target=target, variables=variables, debug=payload.debug)
        dpmm, width_in, height_in = _target_to_labelary_args(payload.target)
        image_bytes = render_labelary_png_bytes(
            zpl,
            dpmm=dpmm,
            label_width_in=width_in,
            label_height_in=height_in,
            index=0,
            timeout_s=30,
        )
        return Response(content=image_bytes, media_type="image/png")
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class PrintZplRequest(BaseModel):
    zpl: str
    return_preview: bool = False


class PrintTemplateRequest(BaseModel):
    template: dict[str, Any]
    variables: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False
    target: Optional[RenderTarget] = None
    return_preview: bool = False


class PrintResponse(BaseModel):
    printer_id: str
    bytes_sent: int
    preview_png_base64: Optional[str] = None


class PrinterStatusResponse(BaseModel):
    printer_id: str
    raw: dict[str, str]
    parsed: dict[str, Any]
    normalized: dict[str, Any]


class PrintDraftCreateRequest(BaseModel):
    template: dict[str, Any]
    variables: dict[str, Any] = Field(default_factory=dict)
    target: RenderTarget
    debug: bool = False


class PrintDraftResponse(BaseModel):
    draft_id: str
    expires_at: str


class PrintDraftDetailResponse(BaseModel):
    draft_id: str
    template: dict[str, Any]
    variables: dict[str, Any]
    target: RenderTarget
    debug: bool
    created_at: str
    expires_at: str


class TemplateSaveRequest(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    variables: list[dict[str, Any]] = Field(default_factory=list)
    template: dict[str, Any]
    sample_data: dict[str, Any]
    preview_target: RenderTarget


class TemplateListItem(BaseModel):
    id: str
    name: str
    tags: list[str]
    variables: list[dict[str, Any]]
    preview_target: dict[str, Any]
    preview_available: bool


class TemplateDetailResponse(BaseModel):
    id: str
    name: str
    tags: list[str]
    variables: list[dict[str, Any]]
    preview_target: dict[str, Any]
    preview_available: bool
    template: dict[str, Any]
    sample_data: dict[str, Any]


def _get_printer(printer_id: str) -> dict[str, Any]:
    config = getattr(app.state, 'printers_config', None) or load_printers_config()
    app.state.printers_config = config
    for printer in config.get('printers', []):
        if printer.get('id') == printer_id:
            return printer
    raise HTTPException(status_code=404, detail=f'Printer not found: {printer_id}')


def _ensure_printer_enabled(printer: Mapping[str, Any]) -> None:
    if not printer.get('enabled', True):
        raise HTTPException(status_code=409, detail='Printer is disabled')


def _ensure_printer_supports_status(printer: Mapping[str, Any]) -> None:
    caps = printer.get('capabilities') or {}
    if not caps.get('supports_status', False):
        raise HTTPException(status_code=409, detail='Printer status is not supported')


def _printer_target(printer: Mapping[str, Any]) -> RenderTarget:
    media_loaded = (printer.get('media') or {}).get('loaded') or {}
    alignment = printer.get('alignment') or {}
    try:
        width_mm = float(media_loaded['width_mm'])
        height_mm = float(media_loaded['height_mm'])
        dpi = int(alignment['dpi'])
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f'Missing printer alignment/media field: {exc.args[0]}') from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail='Invalid printer alignment/media field types') from exc
    return RenderTarget(
        width_mm=width_mm,
        height_mm=height_mm,
        dpi=dpi,
        origin_x_mm=float(alignment.get('offset_x_mm', 0.0)),
        origin_y_mm=float(alignment.get('offset_y_mm', 0.0)),
    )


def _printer_labelary_args(printer: Mapping[str, Any]) -> tuple[int, float, float]:
    target = _printer_target(printer)
    return _target_to_labelary_args(target)


def _render_preview_or_error(zpl: str, *, dpmm: int, width_in: float, height_in: float, return_preview: bool) -> Optional[str]:
    if not return_preview:
        return None
    if not _labelary_preview_enabled():
        raise HTTPException(status_code=403, detail='Labelary preview is disabled')
    try:
        image_bytes = render_labelary_png_bytes(
            zpl,
            dpmm=dpmm,
            label_width_in=width_in,
            label_height_in=height_in,
            index=0,
            timeout_s=30,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return base64.b64encode(image_bytes).decode('ascii')


def _clean_status_text(text: str) -> str:
    cleaned = text.replace('\x02', '').replace('\x03', '')
    return cleaned.strip()


def _parse_host_status(raw: str) -> list[list[str]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return [line.split(',') for line in lines]


def _parse_host_diagnostic(raw: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in raw.splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            info[key.strip()] = value.strip()
    return info


def _parse_host_identification(raw: str) -> dict[str, str]:
    parts = [p.strip() for p in raw.split(',') if p.strip()]
    result: dict[str, str] = {}
    if len(parts) >= 1:
        result['model'] = parts[0]
    if len(parts) >= 2:
        result['firmware'] = parts[1]
    if len(parts) >= 3:
        result['dpmm'] = parts[2]
    if len(parts) >= 4:
        result['memory'] = parts[3]
    return result


def _parse_host_inventory(raw: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith('ERRORS:'):
            _, rest = line.split(':', 1)
            info['errors'] = rest.strip()
        elif line.startswith('WARNINGS:'):
            _, rest = line.split(':', 1)
            info['warnings'] = rest.strip()
    return info


def _parse_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _split_status_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    parts = [part.strip() for part in value.replace(';', ',').split(',')]
    return [part for part in parts if part and part.lower() not in ('none', 'n/a', 'na')]


def _normalize_host_status(raw: str) -> dict[str, Any]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    normalized_lines: list[dict[str, Any]] = []
    for line in lines:
        fields = [field.strip() for field in line.split(',')]
        field_entries: list[dict[str, Any]] = []
        for idx, field in enumerate(fields):
            entry: dict[str, Any] = {'index': idx, 'value': field}
            value_int = _parse_int(field)
            if value_int is not None:
                entry['value_int'] = value_int
            field_entries.append(entry)
        normalized_lines.append(
            {
                'raw': line,
                'fields': field_entries,
                'field_count': len(fields),
            }
        )
    return {'lines': normalized_lines}


def _normalize_host_diagnostic(raw: str) -> dict[str, Any]:
    parsed = _parse_host_diagnostic(raw)
    entries = [{'key': key, 'value': value} for key, value in parsed.items()]
    return {'map': parsed, 'entries': entries}


def _normalize_host_identification(raw: str) -> dict[str, Any]:
    parsed = _parse_host_identification(raw)
    dpmm_raw = parsed.get('dpmm')
    dpmm = _parse_int(dpmm_raw) if isinstance(dpmm_raw, str) else None
    return {
        'model': parsed.get('model'),
        'firmware': parsed.get('firmware'),
        'dpmm': dpmm,
        'dpmm_raw': dpmm_raw,
        'memory': parsed.get('memory'),
    }


def _normalize_host_inventory(raw: str) -> dict[str, Any]:
    parsed = _parse_host_inventory(raw)
    errors = _split_status_list(parsed.get('errors'))
    warnings = _split_status_list(parsed.get('warnings'))
    return {
        'errors': errors,
        'warnings': warnings,
        'has_errors': bool(errors),
        'has_warnings': bool(warnings),
    }


def _build_status_summary(normalized: Mapping[str, Any]) -> dict[str, Any]:
    identification = normalized.get('host_identification') or {}
    inventory = normalized.get('host_inventory') or {}
    errors = list(inventory.get('errors') or [])
    warnings = list(inventory.get('warnings') or [])
    return {
        'model': identification.get('model'),
        'firmware': identification.get('firmware'),
        'dpmm': identification.get('dpmm'),
        'memory': identification.get('memory'),
        'errors': errors,
        'warnings': warnings,
        'has_errors': bool(errors),
        'has_warnings': bool(warnings),
    }


def _normalize_status_payload(raw_results: Mapping[str, str]) -> dict[str, Any]:
    host_status_raw = raw_results.get('host_status', '')
    host_diagnostic_raw = raw_results.get('host_diagnostic', '')
    host_identification_raw = raw_results.get('host_identification', '')
    host_inventory_raw = raw_results.get('host_inventory', '')
    normalized = {
        'host_status': _normalize_host_status(host_status_raw),
        'host_diagnostic': _normalize_host_diagnostic(host_diagnostic_raw),
        'host_identification': _normalize_host_identification(host_identification_raw),
        'host_inventory': _normalize_host_inventory(host_inventory_raw),
    }
    normalized['summary'] = _build_status_summary(normalized)
    return normalized


@app.post("/v1/printers/{printer_id}/prints/zpl", response_model=PrintResponse)
def print_zpl(printer_id: str, payload: PrintZplRequest) -> PrintResponse:
    printer = _get_printer(printer_id)
    _ensure_printer_enabled(printer)
    zpl_with_settings = apply_printer_settings(payload.zpl, printer)
    try:
        bytes_sent = send_raw_zpl(printer, zpl_with_settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    dpmm, width_in, height_in = _printer_labelary_args(printer)
    preview = _render_preview_or_error(
        payload.zpl,
        dpmm=dpmm,
        width_in=width_in,
        height_in=height_in,
        return_preview=payload.return_preview,
    )
    return PrintResponse(printer_id=printer_id, bytes_sent=bytes_sent, preview_png_base64=preview)


@app.post("/v1/drafts", response_model=PrintDraftResponse)
def create_print_draft(payload: PrintDraftCreateRequest) -> PrintDraftResponse:
    try:
        template = load_template(payload.template)
        used_names = collect_template_placeholders(template)
        macro_vars = build_macro_variables(
            used_names,
            existing_variables=payload.variables,
            context=MacroContext(
                template_name=str(payload.template.get('name')) if isinstance(payload.template, dict) else None,
                printer_id=None,
                draft_id=None,
                now=now_for_macros(),
                increment_counters=False,
            ),
        )
        _assert_variables_present(template, {**macro_vars, **payload.variables})
        entry = save_print_draft(
            template=payload.template,
            variables=payload.variables,
            target=payload.target.model_dump(),
            debug=payload.debug,
        )
        return PrintDraftResponse(
            draft_id=entry.draft_id,
            expires_at=entry.expires_at.isoformat(),
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/drafts/{draft_id}", response_model=PrintDraftDetailResponse)
def get_print_draft(draft_id: str) -> PrintDraftDetailResponse:
    try:
        entry = load_print_draft(draft_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f'Draft not found: {draft_id}') from None
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PrintDraftDetailResponse(
        draft_id=entry.draft_id,
        template=entry.template,
        variables=entry.variables,
        target=RenderTarget(**entry.target),
        debug=entry.debug,
        created_at=entry.created_at.isoformat(),
        expires_at=entry.expires_at.isoformat(),
    )


@app.post("/v1/printers/{printer_id}/prints/template", response_model=PrintResponse)
def print_template(printer_id: str, payload: PrintTemplateRequest) -> PrintResponse:
    printer = _get_printer(printer_id)
    _ensure_printer_enabled(printer)
    try:
        template = load_template(payload.template)
        used_names = collect_template_placeholders(template)
        macro_vars = build_macro_variables(
            used_names,
            existing_variables=payload.variables,
            context=MacroContext(
                template_name=str(payload.template.get('name')) if isinstance(payload.template, dict) else None,
                printer_id=printer_id,
                draft_id=None,
                now=now_for_macros(),
                increment_counters=True,
            ),
        )
        variables = {**macro_vars, **payload.variables}
        _assert_variables_present(template, variables)
        target = payload.target or _printer_target(printer)
        zpl = template.compile(target=LabelTarget(**target.model_dump()), variables=variables, debug=payload.debug)
        zpl_with_settings = apply_printer_settings(zpl, printer)
        bytes_sent = send_raw_zpl(printer, zpl_with_settings)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    dpmm, width_in, height_in = _target_to_labelary_args(target)
    preview = _render_preview_or_error(
        zpl,
        dpmm=dpmm,
        width_in=width_in,
        height_in=height_in,
        return_preview=payload.return_preview,
    )
    return PrintResponse(printer_id=printer_id, bytes_sent=bytes_sent, preview_png_base64=preview)


@app.get("/v1/printers/{printer_id}/status", response_model=PrinterStatusResponse)
def get_printer_status(printer_id: str) -> PrinterStatusResponse:
    printer = _get_printer(printer_id)
    _ensure_printer_enabled(printer)
    _ensure_printer_supports_status(printer)

    commands = {
        'host_status': '~HS',
        'host_diagnostic': '~HD',
        'host_identification': '~HI',
        'host_inventory': '~HQES',
    }

    raw_results: dict[str, str] = {}
    parsed_results: dict[str, Any] = {}
    for key, cmd in commands.items():
        try:
            raw_text = _clean_status_text(query_raw_command(printer, cmd))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        raw_results[key] = raw_text
        if key == 'host_status':
            parsed_results[key] = _parse_host_status(raw_text)
        elif key == 'host_diagnostic':
            parsed_results[key] = _parse_host_diagnostic(raw_text)
        elif key == 'host_identification':
            parsed_results[key] = _parse_host_identification(raw_text)
        elif key == 'host_inventory':
            parsed_results[key] = _parse_host_inventory(raw_text)

    normalized_results = _normalize_status_payload(raw_results)
    return PrinterStatusResponse(
        printer_id=printer_id,
        raw=raw_results,
        parsed=parsed_results,
        normalized=normalized_results,
    )


@app.post("/v1/templates", response_model=TemplateDetailResponse)
def save_template(payload: TemplateSaveRequest) -> TemplateDetailResponse:
    try:
        template = load_template(payload.template)
        used_names = collect_template_placeholders(template)
        macro_vars = build_macro_variables(
            used_names,
            existing_variables=payload.sample_data,
            context=MacroContext(
                template_name=payload.name,
                printer_id=None,
                draft_id=None,
                now=now_for_macros(),
                increment_counters=False,
            ),
        )
        variables = {**macro_vars, **payload.sample_data}
        _assert_variables_present(template, variables)
        preview_png = None
        if _labelary_templates_enabled():
            target = LabelTarget(
                width_mm=payload.preview_target.width_mm,
                height_mm=payload.preview_target.height_mm,
                dpi=payload.preview_target.dpi,
                origin_x_mm=payload.preview_target.origin_x_mm,
                origin_y_mm=payload.preview_target.origin_y_mm,
            )
            zpl = template.compile(target=target, variables=variables, debug=False)
            dpmm, width_in, height_in = _target_to_labelary_args(payload.preview_target)
            preview_png = render_labelary_png_bytes(
                zpl,
                dpmm=dpmm,
                label_width_in=width_in,
                label_height_in=height_in,
                index=0,
                timeout_s=30,
            )
        entry = save_template_entry(
            name=payload.name,
            tags=payload.tags,
            variables=payload.variables,
            preview_target=payload.preview_target.model_dump(),
            template=payload.template,
            sample_data=payload.sample_data,
            preview_png=preview_png,
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    template_path = entry.template_path
    sample_path = entry.sample_data_path
    template_json = json.loads(template_path.read_text(encoding='utf-8'))
    sample_json = json.loads(sample_path.read_text(encoding='utf-8'))
    return TemplateDetailResponse(
        id=entry.template_id,
        name=entry.name,
        tags=entry.tags,
        variables=entry.variables,
        preview_target=entry.preview_target,
        preview_available=entry.preview_path.exists(),
        template=template_json,
        sample_data=sample_json,
    )


@app.put("/v1/templates/{template_id}", response_model=TemplateDetailResponse)
def update_template(template_id: str, payload: TemplateSaveRequest) -> TemplateDetailResponse:
    try:
        template = load_template(payload.template)
        used_names = collect_template_placeholders(template)
        macro_vars = build_macro_variables(
            used_names,
            existing_variables=payload.sample_data,
            context=MacroContext(
                template_name=payload.name,
                printer_id=None,
                draft_id=None,
                now=now_for_macros(),
                increment_counters=False,
            ),
        )
        variables = {**macro_vars, **payload.sample_data}
        _assert_variables_present(template, variables)
        preview_png = None
        if _labelary_templates_enabled():
            target = LabelTarget(
                width_mm=payload.preview_target.width_mm,
                height_mm=payload.preview_target.height_mm,
                dpi=payload.preview_target.dpi,
                origin_x_mm=payload.preview_target.origin_x_mm,
                origin_y_mm=payload.preview_target.origin_y_mm,
            )
            zpl = template.compile(target=target, variables=variables, debug=False)
            dpmm, width_in, height_in = _target_to_labelary_args(payload.preview_target)
            preview_png = render_labelary_png_bytes(
                zpl,
                dpmm=dpmm,
                label_width_in=width_in,
                label_height_in=height_in,
                index=0,
                timeout_s=30,
            )
        entry = update_template_entry(
            template_id=template_id,
            name=payload.name,
            tags=payload.tags,
            variables=payload.variables,
            preview_target=payload.preview_target.model_dump(),
            template=payload.template,
            sample_data=payload.sample_data,
            preview_png=preview_png,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f'Template not found: {template_id}') from None
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    template_path = entry.template_path
    sample_path = entry.sample_data_path
    template_json = json.loads(template_path.read_text(encoding='utf-8'))
    sample_json = json.loads(sample_path.read_text(encoding='utf-8'))
    return TemplateDetailResponse(
        id=entry.template_id,
        name=entry.name,
        tags=entry.tags,
        variables=entry.variables,
        preview_target=entry.preview_target,
        preview_available=entry.preview_path.exists(),
        template=template_json,
        sample_data=sample_json,
    )


@app.get("/v1/templates", response_model=list[TemplateListItem])
def list_template_entries(tags: Optional[str] = None) -> list[TemplateListItem]:
    tag_set = None
    if tags:
        tag_set = {tag.strip() for tag in tags.split(',') if tag.strip()}
    entries = list_templates(tags=tag_set)
    result: list[TemplateListItem] = []
    for entry in entries:
        result.append(
            TemplateListItem(
                id=entry.template_id,
                name=entry.name,
                tags=entry.tags,
                variables=entry.variables,
                preview_target=entry.preview_target,
                preview_available=entry.preview_path.exists(),
            )
        )
    return result


@app.get("/v1/templates/{template_id}", response_model=TemplateDetailResponse)
def get_template_entry(template_id: str) -> TemplateDetailResponse:
    try:
        entry = load_template_entry(template_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f'Template not found: {template_id}') from None

    try:
        template_json = json.loads(entry.template_path.read_text(encoding='utf-8'))
        sample_json = json.loads(entry.sample_data_path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return TemplateDetailResponse(
        id=entry.template_id,
        name=entry.name,
        tags=entry.tags,
        variables=entry.variables,
        preview_target=entry.preview_target,
        preview_available=entry.preview_path.exists(),
        template=template_json,
        sample_data=sample_json,
    )


@app.get("/v1/templates/{template_id}/preview")
def get_template_preview(template_id: str) -> Response:
    try:
        entry = load_template_entry(template_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f'Template not found: {template_id}') from None

    preview_path = entry.preview_path
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail='Preview not found')
    try:
        image_bytes = preview_path.read_bytes()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(content=image_bytes, media_type="image/png")


@app.get("/v1/printers", response_model=PrintersConfigResponse)
def get_printers() -> PrintersConfigResponse:
    config = getattr(app.state, 'printers_config', None) or load_printers_config()
    app.state.printers_config = config
    return PrintersConfigResponse(**config)


@app.get("/v1/printers/{printer_id}")
def get_printer(printer_id: str) -> dict[str, Any]:
    config = getattr(app.state, 'printers_config', None) or load_printers_config()
    app.state.printers_config = config
    for printer in config.get('printers', []):
        if printer.get('id') == printer_id:
            return printer
    raise HTTPException(status_code=404, detail=f'Printer not found: {printer_id}')


@app.put("/v1/printers/{printer_id}")
def upsert_printer(printer_id: str, payload: dict[str, Any]) -> PrintersConfigResponse:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail='Printer payload must be a JSON object')

    if 'id' in payload and payload.get('id') != printer_id:
        raise HTTPException(status_code=400, detail='Printer id in payload must match path')

    printer = dict(payload)
    printer['id'] = printer_id

    config = getattr(app.state, 'printers_config', None) or load_printers_config()
    printers = list(config.get('printers', []))
    replaced = False
    for idx, existing in enumerate(printers):
        if existing.get('id') == printer_id:
            printers[idx] = printer
            replaced = True
            break
    if not replaced:
        printers.append(printer)

    updated = {
        'config_version': config.get('config_version', 1),
        'printers': printers,
    }
    try:
        save_printers_config(updated)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    app.state.printers_config = updated
    return PrintersConfigResponse(**updated)
