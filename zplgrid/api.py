from __future__ import annotations

import base64
from dataclasses import asdict
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field, model_validator

from .exceptions import CompilationError, LayoutError, TemplateRenderError, TemplateValidationError
from .compiler import Compiler
from .fleet import FleetConflict, HttpPrinterFleetAdapter, PrinterFleetPort, PrintArtifact
from .labelary import render_labelary_png_bytes
from .integration_events import (
    IntegrationEventStore,
    IntegrationEventWorker,
    ThingdexEventPublisher,
    event_id as integration_event_id,
)
from .macros import MacroContext, build_macro_variables, collect_template_placeholders, now_for_macros
from .model import DataMatrixElement, LabelTarget, LeafNode, QrElement, SplitNode, Template, TextElement
from .parser import load_template
from .print_drafts_store import load_print_draft, save_print_draft
from .print_jobs_store import (
    create_job as create_stored_print_job,
    create_raster_job as create_stored_raster_job,
    list_jobs as list_stored_print_jobs,
    load_job as load_stored_print_job,
    load_job_document,
    recover_interrupted_jobs,
    save_job as save_stored_print_job,
)
from .printing.domain import (
    ContentOptimize,
    DitherMode,
    MediaMismatchError,
    RasterPageSource,
    ScalingPolicy,
)
from .printing.documents import SUPPORTED_DOCUMENT_TYPES, prepare_source_document
from .printing.service import (
    dispatch_document as dispatch_raster_document,
    prepare_document as prepare_raster_document,
    target_for_printer,
)
from .render import RenderOptions, render_text
from .templates_store import load_template_entry, list_templates, save_template_entry, seed_bundled_templates, update_template_entry


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


class RenderDiagnostic(BaseModel):
    code: str
    message: str
    severity: str = "warning"
    element_id: str | None = None
    leaf_alias: str | None = None
    actual_lines: int | None = None
    max_lines: int | None = None


class RenderResponse(BaseModel):
    zpl: str
    diagnostics: list[RenderDiagnostic] = Field(default_factory=list)


load_dotenv()

app = FastAPI(title="zplgrid API", version="1.0")

_cors_origins_raw = os.getenv('ZPLGRID_CORS_ORIGINS', '')
_cors_origins = [origin.strip() for origin in _cors_origins_raw.split(',') if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


class PrintersConfigResponse(BaseModel):
    config_version: int
    printers: list[dict[str, Any]]
    default_printer_id: str | None = None


def _integration_event_store() -> IntegrationEventStore:
    configured = os.getenv("PRINTHUB_INTEGRATION_EVENTS_DIR", "").strip()
    path = Path(configured) if configured else Path(
        os.getenv("ZPLGRID_PRINT_JOBS_DIR", "/data/print-jobs")
    ) / "integration-events"
    current = getattr(app.state, "integration_event_store", None)
    if current is None or current.path != path:
        current = IntegrationEventStore(path)
        app.state.integration_event_store = current
    return current


def _record_integration_state(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("origin") != "thingdex" or not job.get("origin_reference"):
        return job
    try:
        intent_id = str(uuid.UUID(str(job["origin_reference"])))
    except ValueError:
        logging.getLogger(__name__).warning(
            "Ignoring Thingdex callback for invalid origin reference on job %s",
            job.get("id"),
        )
        return job
    if job.get("integration_last_state") == job.get("status"):
        return job
    sequence = int(job.get("integration_sequence") or 0) + 1
    occurred_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "event_id": integration_event_id(str(job["id"]), sequence),
        "intent_id": intent_id,
        "sequence": sequence,
        "job_id": str(job["id"]),
        "job_state": str(job["status"]),
        "occurred_at": occurred_at,
        "detail": {
            "downstream_job_id": job.get("downstream_job_id"),
            "downstream_job_state": job.get("downstream_job_state"),
            "error": job.get("error"),
            "warning": job.get("warning"),
        },
    }
    # Persist the event first. A crash before updating the job can only enqueue
    # the same deterministic event again, never lose the state transition.
    _integration_event_store().enqueue(payload)
    updated = dict(job)
    updated["integration_sequence"] = sequence
    updated["integration_last_state"] = job["status"]
    return save_stored_print_job(updated)


@app.on_event("startup")
def initialize_application() -> None:
    recover_interrupted_jobs()
    seed_bundled_templates(os.getenv('ZPLGRID_BUNDLED_TEMPLATES_DIR'))
    fleet_api_url = os.getenv("PRINTHUB_FLEET_API_URL", "").strip()
    if fleet_api_url:
        app.state.fleet_port = HttpPrinterFleetAdapter(fleet_api_url)
    try:
        event_url = os.getenv("PRINTHUB_THINGDEX_EVENT_URL", "").strip()
        event_secret = os.getenv("PRINTHUB_THINGDEX_EVENT_SECRET", "").strip()
        if bool(event_url) != bool(event_secret):
            raise RuntimeError(
                "PRINTHUB_THINGDEX_EVENT_URL and PRINTHUB_THINGDEX_EVENT_SECRET must be configured together"
            )
        if event_url:
            event_worker = IntegrationEventWorker(
                _integration_event_store(),
                ThingdexEventPublisher(event_url, event_secret).publish,
                interval_seconds=float(
                    os.getenv("PRINTHUB_INTEGRATION_EVENT_INTERVAL_SECONDS", "1")
                ),
                max_attempts=int(os.getenv("PRINTHUB_INTEGRATION_EVENT_MAX_ATTEMPTS", "10")),
            )
            app.state.integration_event_worker = event_worker
            event_worker.start()
    except ValueError as exc:
        raise RuntimeError(f'Failed to initialize PrintHub: {exc}') from exc


@app.on_event('shutdown')
def stop_integration_workers() -> None:
    event_worker = getattr(app.state, "integration_event_worker", None)
    if event_worker:
        event_worker.stop()


def _fleet() -> PrinterFleetPort:
    fleet = getattr(app.state, "fleet_port", None)
    if fleet is None:
        fleet_api_url = os.getenv("PRINTHUB_FLEET_API_URL", "").strip()
        if not fleet_api_url:
            raise RuntimeError("PRINTHUB_FLEET_API_URL is required for printer operations")
        fleet = HttpPrinterFleetAdapter(fleet_api_url)
        app.state.fleet_port = fleet
    return fleet


@app.exception_handler(FleetConflict)
async def fleet_conflict_handler(_request, exc: FleetConflict):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={'detail': str(exc)})


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


def _diagnostics_header(diagnostics: list[dict[str, Any]]) -> str:
    payload = json.dumps(diagnostics, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return base64.urlsafe_b64encode(payload).decode('ascii')


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
        result = Compiler().compile_with_diagnostics(template, target=target, variables=variables, debug=payload.debug)
        return RenderResponse(zpl=result.zpl, diagnostics=[asdict(item) for item in result.diagnostics])
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
        result = Compiler().compile_with_diagnostics(template, target=target, variables=variables, debug=payload.debug)
        diagnostics = [asdict(item) for item in result.diagnostics]
        dpmm, width_in, height_in = _target_to_labelary_args(payload.target)
        image_bytes = render_labelary_png_bytes(
            result.zpl,
            dpmm=dpmm,
            label_width_in=width_in,
            label_height_in=height_in,
            index=0,
            timeout_s=30,
        )
        return Response(
            content=image_bytes,
            media_type="image/png",
            headers={
                'X-PrintHub-Diagnostics': _diagnostics_header(diagnostics),
                'Access-Control-Expose-Headers': 'X-PrintHub-Diagnostics',
            },
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


class PrintTemplateRequest(BaseModel):
    template: dict[str, Any]
    variables: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False
    target: Optional[RenderTarget] = None
    return_preview: bool = False
    idempotency_key: Optional[str] = Field(default=None, max_length=240)


class PrintResponse(BaseModel):
    printer_id: str
    bytes_sent: int
    preview_png_base64: Optional[str] = None
    job_id: Optional[str] = None
    job_state: Optional[str] = None


class PrintJobCreateRequest(BaseModel):
    printer_id: str
    template_id: Optional[str] = None
    template: Optional[dict[str, Any]] = None
    variables: dict[str, Any] = Field(default_factory=dict)
    target: Optional[RenderTarget] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=240)
    origin: Optional[str] = Field(default=None, max_length=120)
    origin_reference: Optional[str] = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_one_template_source(self) -> "PrintJobCreateRequest":
        if (self.template_id is None) == (self.template is None):
            raise ValueError("Provide exactly one of template_id or template")
        return self


class RasterPageRequest(BaseModel):
    mime_type: str = Field(pattern="^image/(png|jpeg|x-portable-graymap)$")
    data_base64: str = Field(min_length=1, max_length=48_000_000)
    width_mm: float = Field(gt=0, le=2000)
    height_mm: float = Field(gt=0, le=2000)


class RasterPrintJobCreateRequest(BaseModel):
    printer_id: str = Field(min_length=1, max_length=240)
    pages: list[RasterPageRequest] = Field(min_length=1, max_length=100)
    copies: int = Field(default=1, ge=1, le=999)
    scaling: ScalingPolicy = ScalingPolicy.HOLD
    content_optimize: ContentOptimize = ContentOptimize.AUTO
    dither: DitherMode = DitherMode.AUTO
    mismatch_tolerance_mm: float = Field(default=0.5, ge=0, le=20)
    idempotency_key: Optional[str] = Field(default=None, max_length=240)
    origin: Optional[str] = Field(default=None, max_length=120)
    origin_reference: Optional[str] = Field(default=None, max_length=255)


class DocumentPrintJobCreateRequest(BaseModel):
    printer_id: str = Field(min_length=1, max_length=240)
    mime_type: str = Field(min_length=1, max_length=120)
    data_base64: str = Field(min_length=1, max_length=48_000_000)
    copies: int = Field(default=1, ge=1, le=999)
    scaling: ScalingPolicy = ScalingPolicy.HOLD
    content_optimize: ContentOptimize = ContentOptimize.AUTO
    dither: DitherMode = DitherMode.AUTO
    mismatch_tolerance_mm: float = Field(default=0.5, ge=0, le=20)
    idempotency_key: Optional[str] = Field(default=None, max_length=240)
    origin: Optional[str] = Field(default=None, max_length=120)
    origin_reference: Optional[str] = Field(default=None, max_length=255)


class RasterPrintJobReleaseRequest(BaseModel):
    scaling: ScalingPolicy


class PrintJobResponse(BaseModel):
    id: str
    status: str
    printer_id: str
    template_id: Optional[str] = None
    source_kind: str = "template"
    page_count: Optional[int] = None
    attempts: int
    bytes_sent: Optional[int] = None
    downstream_job_id: Optional[str] = None
    downstream_job_state: Optional[str] = None
    preview_png_base64: Optional[str] = None
    warning: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


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
    """Read a live printer capability snapshot through the fleet boundary."""
    try:
        return _fleet().get_printer(printer_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f'Printer not found: {printer_id}') from None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _ensure_printer_enabled(printer: Mapping[str, Any]) -> None:
    if not printer.get('enabled', True):
        raise HTTPException(status_code=409, detail='Printer is disabled')


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
        dispatched = _fleet().deliver(
            PrintArtifact(
                mime_type="application/zpl",
                payload=zpl.encode("utf-8"),
                description=f"Template: {payload.template.get('name', 'Untitled')}",
                idempotency_key=payload.idempotency_key,
            ),
            printer,
        )
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    dpmm, width_in, height_in = _target_to_labelary_args(target)
    preview = _render_preview_or_error(
        zpl,
        dpmm=dpmm,
        width_in=width_in,
        height_in=height_in,
        return_preview=payload.return_preview,
    )
    return PrintResponse(
        printer_id=printer_id,
        bytes_sent=dispatched.bytes_accepted,
        preview_png_base64=preview,
        job_id=dispatched.delivery_id,
        job_state=dispatched.downstream_state,
    )


def _decode_raster_pages(document: Mapping[str, Any]) -> list[RasterPageSource]:
    maximum_bytes = max(1, int(os.getenv("ZPLGRID_MAX_RASTER_DOCUMENT_BYTES", str(32 * 1024 * 1024))))
    pages: list[RasterPageSource] = []
    total_bytes = 0
    for page in document.get("pages") or []:
        try:
            data = base64.b64decode(str(page["data_base64"]), validate=True)
            mime_type = str(page["mime_type"])
            width_mm = float(page["width_mm"])
            height_mm = float(page["height_mm"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid persisted raster page") from exc
        total_bytes += len(data)
        if total_bytes > maximum_bytes:
            raise ValueError(f"Raster document exceeds the {maximum_bytes}-byte limit")
        pages.append(
            RasterPageSource(
                data=data,
                mime_type=mime_type,
                width_mm=width_mm,
                height_mm=height_mm,
            )
        )
    if not pages:
        raise ValueError("A raster document must contain at least one page")
    return pages


def _decode_source_document(document: Mapping[str, Any]) -> tuple[bytes, str]:
    try:
        data = base64.b64decode(str(document["data_base64"]), validate=True)
        mime_type = str(document["mime_type"]).split(";", 1)[0].strip().lower()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid persisted source document") from exc
    maximum_bytes = max(
        1, int(os.getenv("ZPLGRID_MAX_SOURCE_DOCUMENT_BYTES", str(32 * 1024 * 1024)))
    )
    if not data or len(data) > maximum_bytes:
        raise ValueError(f"Source document must contain between 1 and {maximum_bytes} bytes")
    if mime_type not in SUPPORTED_DOCUMENT_TYPES:
        raise ValueError(f"Unsupported document MIME type: {mime_type or 'unset'}")
    return data, mime_type


def _process_raster_job(job: dict[str, Any]) -> dict[str, Any]:
    printer = _get_printer(str(job["printer_id"]))
    _ensure_printer_enabled(printer)
    document = load_job_document(str(job["id"]))
    if document.get("kind") == "source_document":
        source, mime_type = _decode_source_document(document)
        pages = list(
            prepare_source_document(
                source,
                mime_type=mime_type,
                target=target_for_printer(printer),
            )
        )
        job["page_count"] = len(pages)
        save_stored_print_job(job)
    else:
        pages = _decode_raster_pages(document)
    ticket = dict(job.get("ticket") or {})
    scaling = ScalingPolicy(str(ticket.get("scaling") or ScalingPolicy.HOLD.value))
    content_optimize = ContentOptimize(str(ticket.get("content_optimize") or ContentOptimize.AUTO.value))
    dither = DitherMode(str(ticket.get("dither") or DitherMode.AUTO.value))
    tolerance = float(ticket.get("mismatch_tolerance_mm", 0.5))
    try:
        prepared = prepare_raster_document(
            printer,
            pages,
            scaling=scaling,
            content_optimize=content_optimize,
            dither=dither,
            mismatch_tolerance_mm=tolerance,
        )
    except MediaMismatchError as exc:
        preview_pages = prepare_raster_document(
            printer,
            pages,
            scaling=ScalingPolicy.FIT,
            content_optimize=content_optimize,
            dither=dither,
            mismatch_tolerance_mm=tolerance,
        )
        job["status"] = "held"
        job["warning"] = str(exc)
        job["preview_png_base64"] = base64.b64encode(preview_pages[0].preview_png).decode("ascii")
        return save_stored_print_job(job)

    delivery_attempt = int(job.get("delivery_attempts") or 0) + 1
    job["delivery_attempts"] = delivery_attempt
    save_stored_print_job(job)
    dispatched = dispatch_raster_document(
        printer,
        prepared,
        copies=int(ticket.get("copies", 1)),
        delivery_port=_fleet(),
        idempotency_key_prefix=f"{job['id']}/attempt-{delivery_attempt}",
    )
    job["status"] = "queued" if dispatched.downstream_job_ids else "sent"
    job["bytes_sent"] = dispatched.bytes_sent
    job["downstream_job_id"] = dispatched.downstream_job_ids[0] if dispatched.downstream_job_ids else None
    job["downstream_job_state"] = dispatched.downstream_job_states[0] if dispatched.downstream_job_states else None
    job["preview_png_base64"] = base64.b64encode(dispatched.previews[0]).decode("ascii")
    job["warning"] = None
    return save_stored_print_job(job)


def _process_stored_print_job(job: dict[str, Any]) -> dict[str, Any]:
    job = dict(job)
    job["attempts"] = int(job.get("attempts") or 0) + 1
    job["status"] = "processing"
    job["error"] = None
    save_stored_print_job(job)
    try:
        if job.get("source_kind") in {"raster", "document"}:
            return _record_integration_state(_process_raster_job(job))
        if job.get("source_kind") == "inline_template":
            template_json = dict(job["template"])
        else:
            entry = load_template_entry(str(job["template_id"]))
            template_json = json.loads(entry.template_path.read_text(encoding="utf-8"))
        target_payload = job.get("target")
        delivery_attempt = int(job.get("delivery_attempts") or 0) + 1
        job["delivery_attempts"] = delivery_attempt
        save_stored_print_job(job)
        response = print_template(
            str(job["printer_id"]),
            PrintTemplateRequest(
                template=template_json,
                variables=dict(job.get("variables") or {}),
                target=RenderTarget(**target_payload) if isinstance(target_payload, dict) else None,
                return_preview=False,
                idempotency_key=f"{job['id']}/attempt-{delivery_attempt}",
            ),
        )
        job["status"] = "queued" if response.job_id else "sent"
        job["bytes_sent"] = response.bytes_sent
        job["downstream_job_id"] = response.job_id
        job["downstream_job_state"] = response.job_state
    except (FileNotFoundError, ValueError, OSError, RuntimeError, HTTPException) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        job["status"] = "failed"
        job["error"] = str(detail)
    return _record_integration_state(save_stored_print_job(job))


@app.post("/v1/print-jobs", response_model=PrintJobResponse, status_code=202)
def create_print_job(payload: PrintJobCreateRequest) -> PrintJobResponse:
    stored = create_stored_print_job(
        printer_id=payload.printer_id,
        template_id=payload.template_id,
        template=payload.template,
        variables=payload.variables,
        target=payload.target.model_dump() if payload.target else None,
        idempotency_key=payload.idempotency_key,
        origin=payload.origin,
        origin_reference=payload.origin_reference,
    )
    if int(stored.get("attempts") or 0) > 0:
        return PrintJobResponse(**stored)
    return PrintJobResponse(**_process_stored_print_job(stored))


@app.post("/v1/print-jobs/raster", response_model=PrintJobResponse, status_code=202)
def create_raster_print_job(payload: RasterPrintJobCreateRequest) -> PrintJobResponse:
    document = {
        "schema_version": 1,
        "kind": "raster",
        "pages": [page.model_dump(mode="json") for page in payload.pages],
    }
    try:
        _decode_raster_pages(document)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ticket = {
        "copies": payload.copies,
        "scaling": payload.scaling.value,
        "content_optimize": payload.content_optimize.value,
        "dither": payload.dither.value,
        "mismatch_tolerance_mm": payload.mismatch_tolerance_mm,
    }
    stored = create_stored_raster_job(
        printer_id=payload.printer_id,
        document=document,
        ticket=ticket,
        idempotency_key=payload.idempotency_key,
        origin=payload.origin,
        origin_reference=payload.origin_reference,
    )
    if int(stored.get("attempts") or 0) > 0:
        return PrintJobResponse(**stored)
    return PrintJobResponse(**_process_stored_print_job(stored))


@app.post("/v1/print-jobs/documents", response_model=PrintJobResponse, status_code=202)
def create_document_print_job(payload: DocumentPrintJobCreateRequest) -> PrintJobResponse:
    document = {
        "schema_version": 1,
        "kind": "source_document",
        "mime_type": payload.mime_type.split(";", 1)[0].strip().lower(),
        "data_base64": payload.data_base64,
    }
    try:
        _decode_source_document(document)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ticket = {
        "copies": payload.copies,
        "scaling": payload.scaling.value,
        "content_optimize": payload.content_optimize.value,
        "dither": payload.dither.value,
        "mismatch_tolerance_mm": payload.mismatch_tolerance_mm,
    }
    stored = create_stored_raster_job(
        printer_id=payload.printer_id,
        document=document,
        ticket=ticket,
        idempotency_key=payload.idempotency_key,
        origin=payload.origin,
        origin_reference=payload.origin_reference,
    )
    if int(stored.get("attempts") or 0) > 0:
        return PrintJobResponse(**stored)
    return PrintJobResponse(**_process_stored_print_job(stored))


@app.get("/v1/print-jobs", response_model=list[PrintJobResponse])
def get_print_jobs(limit: int = 50) -> list[PrintJobResponse]:
    return [PrintJobResponse(**job) for job in list_stored_print_jobs(limit)]


@app.get("/v1/print-jobs/{job_id}", response_model=PrintJobResponse)
def get_print_job(job_id: str) -> PrintJobResponse:
    try:
        return PrintJobResponse(**load_stored_print_job(job_id))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Print job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/print-jobs/{job_id}/release", response_model=PrintJobResponse)
def release_print_job(job_id: str, payload: RasterPrintJobReleaseRequest) -> PrintJobResponse:
    if payload.scaling is ScalingPolicy.HOLD:
        raise HTTPException(status_code=400, detail="Release requires scaling fit or fill")
    try:
        job = load_stored_print_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Print job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job.get("source_kind") not in {"raster", "document"} or job.get("status") != "held":
        raise HTTPException(status_code=409, detail="Only held document jobs can be released")
    job["ticket"] = {**dict(job.get("ticket") or {}), "scaling": payload.scaling.value}
    job["status"] = "queued"
    job["warning"] = None
    save_stored_print_job(job)
    return PrintJobResponse(**_process_stored_print_job(job))


@app.post("/v1/print-jobs/{job_id}/retry", response_model=PrintJobResponse)
def retry_print_job(job_id: str) -> PrintJobResponse:
    try:
        job = load_stored_print_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Print job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job.get("status") not in {"failed", "outcome_unknown"}:
        raise HTTPException(status_code=409, detail="Only failed print jobs can be retried")
    return PrintJobResponse(**_process_stored_print_job(job))


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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
    try:
        printers = _fleet().list_printers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    requested = os.getenv('ZPLGRID_DEFAULT_PRINTER_ID')
    enabled = [p['id'] for p in printers if p.get('enabled', True)]
    default = requested if requested in enabled else next(iter(enabled), None)
    return PrintersConfigResponse(config_version=1, printers=printers, default_printer_id=default)


@app.get("/v1/printers/{printer_id}")
def get_printer(printer_id: str) -> dict[str, Any]:
    return _get_printer(printer_id)
