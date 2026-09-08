from __future__ import annotations

import base64
from dataclasses import asdict
import json
import logging
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr, model_validator

from .exceptions import CompilationError, LayoutError, TemplateRenderError, TemplateValidationError
from .compiler import Compiler
from .printer_services import (
    DeliveryState,
    HttpPrintServiceAdapter,
    PrinterServicePort,
    PrinterServiceRegistry,
    PrintArtifact,
    ServiceConflict,
    ServiceUnavailable,
)
from .labelary import render_labelary_png_bytes
from .integration_events import (
    IntegrationEventStore,
    IntegrationEventWorker,
    ThingdexEventPublisher,
    event_id as integration_event_id,
)
from .ipp_shares import list_shares, save_share, set_share_enabled
from .macros import MacroContext, build_macro_variables, collect_template_placeholders, now_for_macros
from .model import DataMatrixElement, LabelTarget, LeafNode, QrElement, SplitNode, Template, TextElement
from .parser import load_template
from .print_drafts_store import load_print_draft, save_print_draft
from .print_jobs_store import (
    claim_job as claim_stored_print_job,
    create_job as create_stored_print_job,
    create_raster_job as create_stored_raster_job,
    create_artifact_reprint,
    IdempotencyConflict,
    list_all_jobs as list_all_stored_print_jobs,
    list_jobs as list_stored_print_jobs,
    load_job_artifacts,
    load_job as load_stored_print_job,
    load_job_document,
    recover_interrupted_jobs,
    save_job_artifacts,
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
from .printing.limits import evaluate_label_limit
from .printing.service import (
    dispatch_document as dispatch_raster_document,
    prepare_document as prepare_raster_document,
    target_for_printer,
)
from .printing.raster import encode_prepared_raster, prepare_raster_page
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


class PrinterServiceCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=8, max_length=2000)
    token: SecretStr


class PrinterServiceUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=8, max_length=2000)
    token: SecretStr | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if all(
            value is None
            for value in (self.display_name, self.base_url, self.token, self.enabled)
        ):
            raise ValueError("At least one service property is required")
        return self


class PrinterCatalogUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    visible: bool | None = None
    default: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if self.display_name is None and self.visible is None and self.default is None:
            raise ValueError("At least one printer property is required")
        return self


class ZebraPrinterSaveRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    transport: str = Field(pattern="^(tcp|char_device|usb_bulk)$")
    tcp_host: str | None = Field(default=None, max_length=253)
    tcp_port: int = Field(default=9100, ge=1, le=65535)
    device: str = Field(default="", max_length=1000)
    usb_vendor_id: int | None = Field(default=None, ge=0, le=65535)
    usb_product_id: int | None = Field(default=None, ge=0, le=65535)
    usb_serial: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "tcp" and not (self.tcp_host or "").strip():
            raise ValueError("TCP printers require a host name or IP address")
        if self.transport == "char_device" and not self.device.strip():
            raise ValueError("Character-device printers require a device path")
        if self.transport == "usb_bulk" and (
            self.usb_vendor_id is None or self.usb_product_id is None
        ):
            raise ValueError("USB bulk printers require vendor and product IDs")
        return self


class IppShareSaveRequest(BaseModel):
    printer_id: str = Field(min_length=1, max_length=240)
    display_name: str = Field(min_length=1, max_length=200)
    enabled: bool = True


class IppShareUpdateRequest(BaseModel):
    enabled: bool


def _admin_token() -> str:
    inline = os.getenv("PRINTHUB_ADMIN_TOKEN", "").strip()
    path = os.getenv("PRINTHUB_ADMIN_TOKEN_FILE", "").strip()
    if inline and path:
        raise HTTPException(status_code=503, detail="Configure one PrintHub admin token source")
    try:
        token = Path(path).read_text(encoding="utf-8").strip() if path else inline
    except OSError as exc:
        raise HTTPException(status_code=503, detail="PrintHub admin token is unavailable") from exc
    if len(token) < 24 or any(character.isspace() for character in token):
        raise HTTPException(status_code=503, detail="PrintHub administration is not configured")
    return token


def require_admin(authorization: str | None = Header(default=None)) -> None:
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not secrets.compare_digest(supplied, _admin_token()):
        raise HTTPException(status_code=401, detail="A valid PrintHub admin token is required")


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
            "downstream_jobs": job.get("downstream_jobs") or [],
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
    app.state.printer_service_port = PrinterServiceRegistry.from_environment()
    if _background_jobs_enabled():
        print_worker = PrintJobWorker(
            interval_seconds=float(os.getenv("PRINTHUB_PRINT_WORKER_INTERVAL_SECONDS", "1"))
        )
        app.state.print_job_worker = print_worker
        print_worker.start()
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
    print_worker = getattr(app.state, "print_job_worker", None)
    if print_worker:
        print_worker.stop()
    event_worker = getattr(app.state, "integration_event_worker", None)
    if event_worker:
        event_worker.stop()


def _printer_services() -> PrinterServicePort:
    service = getattr(app.state, "printer_service_port", None)
    if service is None:
        service = PrinterServiceRegistry.from_environment()
        app.state.printer_service_port = service
    return service


def _service_registry() -> PrinterServiceRegistry:
    registry = _printer_services()
    if not isinstance(registry, PrinterServiceRegistry):
        raise RuntimeError("Persistent print-service management is unavailable")
    return registry


@app.exception_handler(ServiceConflict)
async def service_conflict_handler(_request, exc: ServiceConflict):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={'detail': str(exc)})


@app.exception_handler(IdempotencyConflict)
async def idempotency_conflict_handler(_request, exc: IdempotencyConflict):
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
    output_mode: Literal["auto", "native", "raster"] = "auto"
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
    override_label_limit: bool = False


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
    override_label_limit: bool = False


class RasterPrintJobReleaseRequest(BaseModel):
    scaling: ScalingPolicy
    override_label_limit: bool = False


class ReprintRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=240)


class DownstreamJobResponse(BaseModel):
    id: str
    state: str
    bytes_accepted: int = 0
    error: Optional[str] = None


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
    downstream_jobs: list[DownstreamJobResponse] = Field(default_factory=list)
    preview_png_base64: Optional[str] = None
    warning: Optional[str] = None
    hold_reason: Optional[str] = None
    requested_labels: Optional[int] = None
    max_labels: Optional[int] = None
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
    """Read a live printer capability snapshot through its print service."""
    try:
        return _printer_services().get_printer(printer_id)
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
        dispatched = _printer_services().deliver(
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


def _downstream_job_records(
    job_ids: tuple[str, ...], job_states: tuple[str, ...]
) -> list[dict[str, Any]]:
    return [
        {
            "id": job_id,
            "state": job_states[index] if index < len(job_states) else "queued",
            "bytes_accepted": 0,
            "error": None,
        }
        for index, job_id in enumerate(job_ids)
    ]


def _process_raster_job(job: dict[str, Any]) -> dict[str, Any]:
    printer = _get_printer(str(job["printer_id"]))
    _ensure_printer_enabled(printer)
    existing_artifacts = load_job_artifacts(str(job["id"]))
    if existing_artifacts is not None:
        job["delivery_attempts"] = int(job.get("delivery_attempts") or 0) + 1
        save_stored_print_job(job)
        receipt = _dispatch_template_artifact_set(job, printer, existing_artifacts)
        job["status"] = "queued" if receipt.delivery_id else "sent"
        job["bytes_sent"] = receipt.bytes_accepted
        job["downstream_job_id"] = receipt.delivery_id
        job["downstream_job_state"] = receipt.downstream_state
        job["downstream_jobs"] = (
            [
                {
                    "id": receipt.delivery_id,
                    "state": receipt.downstream_state or receipt.state.value,
                    "bytes_accepted": receipt.bytes_accepted,
                    "error": receipt.error,
                }
            ]
            if receipt.delivery_id
            else []
        )
        job["error"] = receipt.error
        return save_stored_print_job(job)
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
    copies = int(ticket.get("copies", 1))
    scaling = ScalingPolicy(str(ticket.get("scaling") or ScalingPolicy.HOLD.value))
    content_optimize = ContentOptimize(str(ticket.get("content_optimize") or ContentOptimize.AUTO.value))
    dither = DitherMode(str(ticket.get("dither") or DitherMode.AUTO.value))
    tolerance = float(ticket.get("mismatch_tolerance_mm", 0.5))
    limit = evaluate_label_limit(pages=len(pages), copies=copies)
    if limit.exceeded and not bool(ticket.get("override_label_limit")):
        preview_pages = prepare_raster_document(
            printer,
            pages,
            scaling=ScalingPolicy.FIT,
            content_optimize=content_optimize,
            dither=dither,
            mismatch_tolerance_mm=tolerance,
        )
        job["status"] = "held"
        job["hold_reason"] = "label_limit_exceeded"
        job["requested_labels"] = limit.requested_labels
        job["max_labels"] = limit.max_labels
        job["warning"] = limit.message
        job["preview_png_base64"] = base64.b64encode(
            preview_pages[0].preview_png
        ).decode("ascii")
        return save_stored_print_job(job)
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
        job["hold_reason"] = "media_mismatch"
        job["warning"] = str(exc)
        job["preview_png_base64"] = base64.b64encode(preview_pages[0].preview_png).decode("ascii")
        return save_stored_print_job(job)

    dispatch_key = str(job.get("dispatch_key") or f"{job['id']}/artifact-v1")
    job["dispatch_key"] = dispatch_key
    artifact_set = {
        "version": 1,
        "copies": copies,
        "media_revision": (printer.get("media") or {}).get("revision"),
        "description": "Prepared raster document",
        "artifacts": [
            {
                "mime_type": "application/vnd.printhub.raster-page+json",
                "data_base64": base64.b64encode(
                    encode_prepared_raster(page, copies=1)
                ).decode("ascii"),
                "description": "Prepared raster document",
            }
            for page in prepared
        ],
    }
    save_job_artifacts(str(job["id"]), artifact_set)
    delivery_attempt = int(job.get("delivery_attempts") or 0) + 1
    job["delivery_attempts"] = delivery_attempt
    save_stored_print_job(job)
    dispatched = dispatch_raster_document(
        printer,
        prepared,
        copies=copies,
        delivery_port=_printer_services(),
        idempotency_key_prefix=dispatch_key,
    )
    job["status"] = "queued" if dispatched.downstream_job_ids else "sent"
    job["bytes_sent"] = dispatched.bytes_sent
    job["downstream_job_id"] = dispatched.downstream_job_ids[0] if dispatched.downstream_job_ids else None
    job["downstream_job_state"] = dispatched.downstream_job_states[0] if dispatched.downstream_job_states else None
    job["downstream_jobs"] = _downstream_job_records(
        dispatched.downstream_job_ids,
        dispatched.downstream_job_states,
    )
    job["preview_png_base64"] = base64.b64encode(dispatched.previews[0]).decode("ascii")
    job["warning"] = None
    job["hold_reason"] = None
    job["requested_labels"] = limit.requested_labels
    job["max_labels"] = limit.max_labels
    return save_stored_print_job(job)


def _prepare_template_artifact_set(
    job: dict[str, Any], printer: Mapping[str, Any]
) -> dict[str, Any]:
    existing = load_job_artifacts(str(job["id"]))
    if existing is not None:
        return existing
    if job.get("source_kind") == "inline_template":
        template_json = dict(job["template"])
    else:
        entry = load_template_entry(str(job["template_id"]))
        template_json = json.loads(entry.template_path.read_text(encoding="utf-8"))
    template = load_template(template_json)
    target_payload = job.get("target")
    target = (
        RenderTarget(**target_payload)
        if isinstance(target_payload, dict)
        else _printer_target(printer)
    )
    resolved = job.get("resolved_variables")
    if not isinstance(resolved, dict):
        supplied = dict(job.get("variables") or {})
        macros = build_macro_variables(
            collect_template_placeholders(template),
            existing_variables=supplied,
            context=MacroContext(
                template_name=str(template_json.get("name") or "Untitled"),
                printer_id=str(job["printer_id"]),
                draft_id=None,
                now=now_for_macros(),
                increment_counters=True,
            ),
        )
        resolved = {**macros, **supplied}
        _assert_variables_present(template, resolved)
        job["resolved_variables"] = resolved
        job["resolved_template"] = template_json
        save_stored_print_job(job)
    zpl = template.compile(
        target=LabelTarget(**target.model_dump()), variables=resolved, debug=False
    )
    accepted = set(printer.get("accepted_mime_types") or ["application/zpl"])
    description = f"Template: {template_json.get('name', 'Untitled')}"
    output_mode = str(job.get("output_mode") or "auto")
    use_native = output_mode == "native" or (
        output_mode == "auto" and "application/zpl" in accepted
    )
    use_raster = output_mode == "raster" or (
        output_mode == "auto"
        and "application/zpl" not in accepted
        and "application/vnd.printhub.raster-page+json" in accepted
    )
    if use_native and "application/zpl" not in accepted:
        raise ValueError("The selected printer does not accept native ZPL")
    if use_raster and "application/vnd.printhub.raster-page+json" not in accepted:
        raise ValueError("The selected printer does not accept the PrintHub raster format")
    if use_native:
        artifact = {
            "mime_type": "application/zpl",
            "data_base64": base64.b64encode(zpl.encode("utf-8")).decode("ascii"),
            "description": description,
        }
    elif use_raster:
        dpmm, width_in, height_in = _target_to_labelary_args(target)
        png = render_labelary_png_bytes(
            zpl,
            dpmm=dpmm,
            label_width_in=width_in,
            label_height_in=height_in,
            index=0,
            timeout_s=30,
        )
        raster_target = target_for_printer(printer)
        prepared = prepare_raster_page(
            RasterPageSource(
                data=png,
                mime_type="image/png",
                width_mm=target.width_mm,
                height_mm=target.height_mm,
            ),
            target=raster_target,
            scaling=ScalingPolicy.HOLD,
            content_optimize=ContentOptimize.TEXT,
            dither=DitherMode.NONE,
            mismatch_tolerance_mm=0.01,
        )
        artifact = {
            "mime_type": "application/vnd.printhub.raster-page+json",
            "data_base64": base64.b64encode(
                encode_prepared_raster(prepared, copies=1)
            ).decode("ascii"),
            "description": description,
        }
    else:
        raise ValueError("Printer accepts neither native ZPL nor the PrintHub raster format")
    artifact_set = {
        "version": 1,
        "copies": 1,
        "media_revision": (printer.get("media") or {}).get("revision"),
        "description": description,
        "artifacts": [artifact],
    }
    save_job_artifacts(str(job["id"]), artifact_set)
    return artifact_set


def _dispatch_template_artifact_set(
    job: dict[str, Any], printer: Mapping[str, Any], artifact_set: Mapping[str, Any]
):
    dispatch_key = str(job.get("dispatch_key") or f"{job['id']}/artifact-v1")
    if job.get("dispatch_key") != dispatch_key:
        job["dispatch_key"] = dispatch_key
        save_stored_print_job(job)
    artifacts = [
        PrintArtifact(
            mime_type=str(item["mime_type"]),
            payload=base64.b64decode(str(item["data_base64"]), validate=True),
            description=str(item.get("description") or artifact_set["description"]),
        )
        for item in artifact_set["artifacts"]
    ]
    return _printer_services().deliver_job(
        artifacts,
        printer,
        copies=int(artifact_set.get("copies") or 1),
        idempotency_key=dispatch_key,
        description=str(artifact_set["description"]),
        media_revision=artifact_set.get("media_revision"),
    )


def _process_stored_print_job(job: dict[str, Any]) -> dict[str, Any]:
    claimed = claim_stored_print_job(str(job["id"]))
    if claimed is None:
        return load_stored_print_job(str(job["id"]))
    job = claimed
    try:
        if job.get("source_kind") in {"raster", "document"}:
            return _record_integration_state(_process_raster_job(job))
        printer = _get_printer(str(job["printer_id"]))
        _ensure_printer_enabled(printer)
        artifact_set = (
            load_job_artifacts(str(job["id"]))
            if job.get("source_kind") == "artifact_reprint"
            else _prepare_template_artifact_set(job, printer)
        )
        if artifact_set is None:
            raise ValueError("Immutable print artifacts are missing")
        job["delivery_attempts"] = int(job.get("delivery_attempts") or 0) + 1
        save_stored_print_job(job)
        response = _dispatch_template_artifact_set(job, printer, artifact_set)
        job["status"] = "queued" if response.delivery_id else "sent"
        job["bytes_sent"] = response.bytes_accepted
        job["downstream_job_id"] = response.delivery_id
        job["downstream_job_state"] = response.downstream_state
        job["downstream_jobs"] = (
            [
                {
                    "id": response.delivery_id,
                    "state": response.downstream_state or "queued",
                    "bytes_accepted": response.bytes_accepted,
                    "error": None,
                }
            ]
            if response.delivery_id
            else []
        )
    except ServiceUnavailable as exc:
        job["status"] = "waiting_for_service"
        job["error"] = str(exc)
    except (
        FileNotFoundError,
        ValueError,
        OSError,
        RuntimeError,
        HTTPException,
        TemplateValidationError,
        TemplateRenderError,
        LayoutError,
        CompilationError,
    ) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        job["status"] = "failed"
        job["error"] = str(detail)
    return _record_integration_state(save_stored_print_job(job))


_PENDING_SERVICE_STATES = {
    DeliveryState.QUEUED,
    DeliveryState.CONNECTING,
    DeliveryState.TRANSMITTING,
    DeliveryState.RETRY_SCHEDULED,
}


def _normalized_delivery_state(value: object) -> DeliveryState:
    """Map protocol-specific downstream states to PrintHub's public state model."""
    aliases = {
        "completed_observed": DeliveryState.CONFIRMED,
        "outcome_unknown": DeliveryState.UNCONFIRMED,
    }
    raw = str(value or DeliveryState.UNCONFIRMED.value)
    if raw in aliases:
        return aliases[raw]
    try:
        return DeliveryState(raw)
    except ValueError:
        return DeliveryState.UNCONFIRMED


def _reconcile_stored_print_jobs(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    job_deliveries: list[list[dict[str, Any]]] = []
    for job in jobs:
        entries = [
            dict(entry)
            for entry in job.get("downstream_jobs") or []
            if isinstance(entry, dict) and entry.get("id")
        ]
        if not entries and job.get("downstream_job_id"):
            entries = [
                {
                    "id": str(job["downstream_job_id"]),
                    "state": str(job.get("downstream_job_state") or "queued"),
                    "bytes_accepted": int(job.get("bytes_sent") or 0),
                    "error": job.get("error"),
                }
            ]
        job_deliveries.append(entries)
    delivery_ids = list(
        dict.fromkeys(str(entry["id"]) for entries in job_deliveries for entry in entries)
    )
    if not delivery_ids:
        return jobs
    try:
        deliveries = _printer_services().get_deliveries(delivery_ids)
    except (OSError, RuntimeError):
        return jobs

    reconciled: list[dict[str, Any]] = []
    for original, entries in zip(jobs, job_deliveries, strict=True):
        job = dict(original)
        if not entries:
            reconciled.append(job)
            continue
        states: list[DeliveryState] = []
        for entry in entries:
            receipt = deliveries.get(str(entry["id"]))
            if receipt is not None:
                entry.update(
                    state=receipt.downstream_state or receipt.state.value,
                    bytes_accepted=receipt.bytes_accepted,
                    error=receipt.error,
                )
                states.append(receipt.state)
            else:
                states.append(_normalized_delivery_state(entry.get("state")))
        if DeliveryState.UNCONFIRMED in states:
            status = DeliveryState.UNCONFIRMED.value
        elif DeliveryState.FAILED in states:
            status = DeliveryState.FAILED.value
        elif any(state in _PENDING_SERVICE_STATES for state in states):
            status = DeliveryState.QUEUED.value
        elif states and all(state is DeliveryState.CANCELLED for state in states):
            status = DeliveryState.CANCELLED.value
        elif DeliveryState.CANCELLED in states:
            status = DeliveryState.UNCONFIRMED.value
        elif DeliveryState.HELD in states:
            status = DeliveryState.HELD.value
        elif states and all(state is DeliveryState.CONFIRMED for state in states):
            status = DeliveryState.CONFIRMED.value
        else:
            status = DeliveryState.TRANSPORT_ACCEPTED.value
        error = next(
            (
                str(entry["error"])
                for entry, state in zip(entries, states, strict=True)
                if entry.get("error")
                and state in {DeliveryState.UNCONFIRMED, DeliveryState.FAILED}
            ),
            None,
        )
        if error is None and status == DeliveryState.UNCONFIRMED.value:
            error = "The print service reports an ambiguous delivery outcome"
        elif error is None and status == DeliveryState.FAILED.value:
            error = "Print-service delivery failed"
        first = entries[0]
        bytes_sent = sum(int(entry.get("bytes_accepted") or 0) for entry in entries)
        changed = any(
            (
                job.get("status") != status,
                job.get("downstream_job_id") != first["id"],
                job.get("downstream_job_state") != first.get("state"),
                job.get("downstream_jobs") != entries,
                job.get("bytes_sent") != bytes_sent,
                job.get("error") != error,
            )
        )
        job.update(
            status=status,
            downstream_job_id=first["id"],
            downstream_job_state=first.get("state"),
            downstream_jobs=entries,
            bytes_sent=bytes_sent,
            error=error,
        )
        reconciled.append(save_stored_print_job(job) if changed else job)
    return reconciled


class PrintJobWorker:
    """Durable scanner: job files are the queue; the event only reduces latency."""

    def __init__(self, interval_seconds: float = 1.0) -> None:
        self.interval_seconds = max(0.1, interval_seconds)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="printhub-print-jobs", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            jobs = list(reversed(list_all_stored_print_jobs()))
            for job in jobs:
                if self._stop.is_set():
                    break
                if job.get("status") in {"queued", "waiting_for_service"} and not job.get(
                    "downstream_job_id"
                ):
                    _process_stored_print_job(job)
            pending = [job for job in jobs if job.get("downstream_job_id")]
            if pending:
                _reconcile_stored_print_jobs(pending)
            self._wake.wait(self.interval_seconds)
            self._wake.clear()


def _background_jobs_enabled() -> bool:
    return os.getenv("PRINTHUB_BACKGROUND_JOBS", "0").strip() == "1"


def _process_or_wake(job: dict[str, Any]) -> dict[str, Any]:
    if not _background_jobs_enabled():
        return _process_stored_print_job(job)
    worker = getattr(app.state, "print_job_worker", None)
    if worker is not None:
        worker.wake()
    return job


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
        output_mode=payload.output_mode,
    )
    if int(stored.get("attempts") or 0) > 0:
        return PrintJobResponse(**_reconcile_stored_print_jobs([stored])[0])
    return PrintJobResponse(**_process_or_wake(stored))


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
        "override_label_limit": payload.override_label_limit,
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
        return PrintJobResponse(**_reconcile_stored_print_jobs([stored])[0])
    return PrintJobResponse(**_process_or_wake(stored))


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
        "override_label_limit": payload.override_label_limit,
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
        return PrintJobResponse(**_reconcile_stored_print_jobs([stored])[0])
    return PrintJobResponse(**_process_or_wake(stored))


@app.get("/v1/print-jobs", response_model=list[PrintJobResponse])
def get_print_jobs(limit: int = 50) -> list[PrintJobResponse]:
    return [
        PrintJobResponse(**job)
        for job in _reconcile_stored_print_jobs(list_stored_print_jobs(limit))
    ]


@app.get("/v1/print-jobs/{job_id}", response_model=PrintJobResponse)
def get_print_job(job_id: str) -> PrintJobResponse:
    try:
        stored = load_stored_print_job(job_id)
        return PrintJobResponse(**_reconcile_stored_print_jobs([stored])[0])
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
    job["ticket"] = {
        **dict(job.get("ticket") or {}),
        "scaling": payload.scaling.value,
        "override_label_limit": payload.override_label_limit,
    }
    job["status"] = "queued"
    job["warning"] = None
    job = save_stored_print_job(job)
    return PrintJobResponse(**_process_or_wake(job))


@app.post("/v1/print-jobs/{job_id}/retry", response_model=PrintJobResponse)
def retry_print_job(job_id: str) -> PrintJobResponse:
    try:
        job = load_stored_print_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Print job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job.get("status") != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only jobs proven not to have printed can be retried; create an explicit reprint for an unknown outcome",
        )
    job["status"] = "queued"
    job["error"] = None
    job = save_stored_print_job(job)
    return PrintJobResponse(**_process_or_wake(job))


@app.post("/v1/print-jobs/{job_id}/cancel", response_model=PrintJobResponse)
def cancel_print_job(job_id: str) -> PrintJobResponse:
    try:
        job = load_stored_print_job(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Print job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = _reconcile_stored_print_jobs([job])[0]
    downstream_ids = [
        str(item["id"])
        for item in job.get("downstream_jobs") or []
        if isinstance(item, dict) and item.get("id")
    ]
    if downstream_ids:
        try:
            receipts = _printer_services().cancel_deliveries(downstream_ids)
        except (OSError, RuntimeError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        entries = []
        for delivery_id in downstream_ids:
            receipt = receipts[delivery_id]
            entries.append(
                {
                    "id": delivery_id,
                    "state": receipt.downstream_state or receipt.state.value,
                    "bytes_accepted": receipt.bytes_accepted,
                    "error": receipt.error,
                }
            )
        job["downstream_jobs"] = entries
        job["downstream_job_state"] = entries[0]["state"]
        job["status"] = "cancelled"
        job["error"] = None
        return PrintJobResponse(**save_stored_print_job(job))
    if job.get("status") not in {"queued", "waiting_for_service", "held", "failed"}:
        raise HTTPException(
            status_code=409,
            detail="The job has already entered delivery and cannot be cancelled safely",
        )
    job["status"] = "cancelled"
    job["error"] = None
    return PrintJobResponse(**save_stored_print_job(job))


@app.post(
    "/v1/print-jobs/{job_id}/reprint",
    response_model=PrintJobResponse,
    status_code=202,
    dependencies=[Depends(require_admin)],
)
def reprint_print_job(job_id: str, payload: ReprintRequest) -> PrintJobResponse:
    try:
        original = load_stored_print_job(job_id)
        if original.get("status") in {"queued", "processing", "waiting_for_service", "held"}:
            raise HTTPException(status_code=409, detail="An active or held job cannot be reprinted")
        job = create_artifact_reprint(original, idempotency_key=payload.idempotency_key)
        return PrintJobResponse(**_process_or_wake(job))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Print job not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        service = _printer_services()
        printers = service.list_printers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    requested = (
        service.default_printer_id()
        if isinstance(service, PrinterServiceRegistry)
        else None
    ) or os.getenv('ZPLGRID_DEFAULT_PRINTER_ID')
    enabled = [p['id'] for p in printers if p.get('enabled', True)]
    default = requested if requested in enabled else next(iter(enabled), None)
    return PrintersConfigResponse(config_version=1, printers=printers, default_printer_id=default)


@app.get("/v1/ipp-shares")
def get_ipp_shares() -> dict[str, Any]:
    return {"items": list_shares()}


@app.put("/v1/ipp-shares/{queue_id}", dependencies=[Depends(require_admin)])
def put_ipp_share(queue_id: str, payload: IppShareSaveRequest) -> dict[str, Any]:
    _get_printer(payload.printer_id)
    try:
        return save_share(
            queue_id,
            printer_id=payload.printer_id,
            display_name=payload.display_name,
            enabled=payload.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.patch("/v1/ipp-shares/{queue_id}", dependencies=[Depends(require_admin)])
def patch_ipp_share(queue_id: str, payload: IppShareUpdateRequest) -> dict[str, Any]:
    try:
        return set_share_enabled(queue_id, payload.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="IPP share not found") from None


@app.get("/v1/printer-services", dependencies=[Depends(require_admin)])
def get_printer_services() -> dict[str, Any]:
    return {"items": _service_registry().list_services()}


@app.post(
    "/v1/printer-services", status_code=201, dependencies=[Depends(require_admin)]
)
def add_printer_service(payload: PrinterServiceCreateRequest) -> dict[str, Any]:
    try:
        return _service_registry().add_service(
            payload.display_name, payload.base_url, payload.token.get_secret_value()
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.patch(
    "/v1/printer-services/{connection_id}", dependencies=[Depends(require_admin)]
)
def update_printer_service(
    connection_id: str, payload: PrinterServiceUpdateRequest
) -> dict[str, Any]:
    try:
        return _service_registry().update_service(
            connection_id,
            display_name=payload.display_name,
            base_url=payload.base_url,
            token=payload.token.get_secret_value() if payload.token else None,
            enabled=payload.enabled,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Print service not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.patch(
    "/v1/printers/{printer_id}/catalog",
    dependencies=[Depends(require_admin)],
)
def update_printer_catalog(
    printer_id: str, payload: PrinterCatalogUpdateRequest
) -> dict[str, Any]:
    try:
        return _service_registry().update_printer_catalog(
            printer_id,
            display_name=payload.display_name,
            visible=payload.visible,
            make_default=payload.default,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Printer not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/v1/printer-services/{connection_id}/printers/{printer_id}",
    dependencies=[Depends(require_admin)],
)
def save_zebra_service_printer(
    connection_id: str, printer_id: str, payload: ZebraPrinterSaveRequest
) -> dict[str, Any]:
    if not printer_id or len(printer_id) > 100 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for character in printer_id
    ):
        raise HTTPException(status_code=400, detail="Printer ID contains unsafe characters")
    try:
        return _service_registry().save_zebra_printer(
            connection_id,
            printer_id,
            {"id": printer_id, "driver": "zpl", **payload.model_dump()},
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Print service not found") from None
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/v1/printer-services/{connection_id}/usb-devices",
    dependencies=[Depends(require_admin)],
)
def discover_service_usb_printers(connection_id: str) -> dict[str, Any]:
    try:
        return {"items": _service_registry().discover_usb_printers(connection_id)}
    except KeyError:
        raise HTTPException(status_code=404, detail="Print service not found") from None
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.put(
    "/v1/printer-services/{connection_id}/printers/{printer_id}/media",
    dependencies=[Depends(require_admin)],
)
def load_zebra_service_media(
    connection_id: str, printer_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    try:
        return _service_registry().load_zebra_media(connection_id, printer_id, payload)
    except KeyError:
        raise HTTPException(status_code=404, detail="Print service not found") from None
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/v1/printer-services/{connection_id}/printers/{printer_id}/queue/{action}",
    dependencies=[Depends(require_admin)],
)
def control_service_printer_queue(
    connection_id: str, printer_id: str, action: str
) -> dict[str, Any]:
    if action not in {"pause", "resume"}:
        raise HTTPException(status_code=400, detail="Queue action must be pause or resume")
    try:
        return _service_registry().set_queue_paused(
            connection_id, printer_id, action == "pause"
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Print service not found") from None
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/v1/printer-services/{connection_id}/printers/{printer_id}/maintenance/{action}",
    dependencies=[Depends(require_admin)],
)
def maintain_service_printer(
    connection_id: str, printer_id: str, action: str
) -> dict[str, Any]:
    if action not in {
        "print-configuration",
        "print-network-configuration",
        "calibrate-media",
    }:
        raise HTTPException(status_code=400, detail="Unsupported maintenance action")
    try:
        return _service_registry().run_maintenance(connection_id, printer_id, action)
    except KeyError:
        raise HTTPException(status_code=404, detail="Print service not found") from None
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/printers/{printer_id}")
def get_printer(printer_id: str) -> dict[str, Any]:
    return _get_printer(printer_id)
