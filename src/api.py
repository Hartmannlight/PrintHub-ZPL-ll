# src/api.py

import logging
import os
import datetime
import shutil
import tempfile
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.config import (
    DEFAULT_FONT,
    COMMON_LABEL_WIDTH,
    COMMON_LABEL_HEIGHT,
    DEFAULT_FONT_SIZE,
)
from src.presets.text_label import TextLabel
from src.presets.qr_label import QRLabel
from src.presets.id_label import IdLabel
from src.presets.cable_type_label import CableTypeLabel
from src.presets.cable_usage_label import CableUsageLabel
from src.presets.container_label import ContainerLabel
from src.presets.food_label import FoodLabel
from src.presets.storage_device_label import StorageDeviceLabel
from src.presets.pcb_label import PcbLabel
from src.presets.power_supply_label import PowerSupplyLabel
from src.presets.micro_controller_label import MicroControllerLabel
from src.presets.network_device_label import NetworkDeviceLabel
from src.presets.lan_cable_label import LanCableLabel
from src.presets.text_header_label import TextHeaderLabel
from src.presets.image_label import ImageLabel

from src.utils.labelary_client import LabelaryClient
from src.printing import get_printer
from src.utils.id_factory import IdFactory

logger = logging.getLogger("printhub_api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(
    title="PrintHub ZPL API",
    description="Generate ZPL-II code, preview PNG, print labels, and manage categories.",
    version="1.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def _handle_output(zpl: str, width_mm: float, height_mm: float, preview: bool) -> Response:
    logger.info(
        "Handling output: width_mm=%s, height_mm=%s, preview=%s",
        width_mm, height_mm, preview
    )
    client = LabelaryClient()
    img_bytes = client.get_label_image(zpl, width_mm, height_mm)

    if not preview:
        printer = get_printer()
        logger.info("Printing to %s using %s", printer.printer_name, type(printer).__name__)
        printer.print(zpl)

        today = datetime.date.today().isoformat()
        save_dir = os.path.join("previews", today)
        os.makedirs(save_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%H%M%S")
        filename = f"preview_{ts}.png"
        path = os.path.join(save_dir, filename)
        with open(path, "wb") as f:
            f.write(img_bytes)
        logger.info("Saved preview: %s", path)

    return Response(content=img_bytes, media_type="image/png")


# --- Request models ---

class TextLabelRequest(BaseModel):
    content: str = Field(..., description="Text to print")
    font: str = Field(DEFAULT_FONT, description="ZPL font identifier")
    font_size: int = Field(DEFAULT_FONT_SIZE, description=f"Font size, default: {DEFAULT_FONT_SIZE}")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0, description="Label width in mm")
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0, description="Label height in mm")


class QRLabelRequest(BaseModel):
    data: str = Field(..., description="QR payload")
    qr_magnification: int = Field(4, gt=0, description="Module magnification")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0, description="Label width in mm")
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0, description="Label height in mm")
    right_text: Optional[str] = Field(None, description="Text to the right")
    bottom_text: Optional[str] = Field(None, description="Text below")
    padding_px: int = Field(5, ge=0, description="Padding in px")


class IdLabelRequest(BaseModel):
    id_category: str = Field(..., description="Category code (e.g. 'NET')")
    id_type: str = Field(..., description="Type code (e.g. 'SRV')")
    module_ratio: int = Field(3, gt=0, description="DataMatrix module ratio")
    padding_x: int = Field(5, ge=0, description="Horizontal padding px")
    padding_y: int = Field(5, ge=0, description="Vertical padding px")
    print_date: bool = Field(True, description="Print date?")
    date_override: Optional[str] = Field(None, description="Override date YYYY-MM-DD")
    date_font_size: int = Field(10, gt=0, description="Date font size")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0, description="Label width in mm")
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0, description="Label height in mm")


class CableTypeLabelRequest(BaseModel):
    from_text: str = Field(..., description="Origin text")
    to_text: str = Field(..., description="Destination text")
    length_cm: float = Field(..., ge=0, description="Length in cm")
    spec_text: Optional[str] = Field(None, description="Specification text")
    id_type: str = Field(..., description="Type code (e.g. 'NTZW')")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class CableUsageLabelRequest(BaseModel):
    from_text: str = Field(..., description="Left column text")
    to_text: str = Field(..., description="Right column text")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class ContainerLabelRequest(BaseModel):
    content: str = Field(..., description="Top text")
    position: str = Field(..., description="Bottom position text")
    id_category: str = Field(..., description="Category for DataMatrix ID")
    id_type: str = Field(..., description="Type for DataMatrix ID")
    module_ratio: int = Field(3, gt=0, description="DataMatrix module ratio")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class FoodLabelRequest(BaseModel):
    bbf_date: str = Field(..., description="Best-before date YYYY-MM-DD")
    food: str = Field(..., description="Food description")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class StorageDeviceLabelRequest(BaseModel):
    size: str = Field(..., description="Storage size")
    info: str = Field(..., description="Additional info")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class PcbLabelRequest(BaseModel):
    project: str = Field(..., description="Project name")
    info: str = Field(..., description="Additional information")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class PowerSupplyLabelRequest(BaseModel):
    volt: str = Field(..., description="Voltage")
    acdc: str = Field(..., description="AC/DC")
    amps: str = Field(..., description="Amperage")
    plug: str = Field(..., description="Plug type")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class MicroControllerLabelRequest(BaseModel):
    mcu_type: str = Field(..., description="Microcontroller type")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class NetworkDeviceLabelRequest(BaseModel):
    device_id: str = Field(..., description="Device DataMatrix ID")
    name: str = Field(..., description="Device name")
    location: str = Field(..., description="Device location")
    ip: str = Field(..., description="Device IP")
    hostname: Optional[str] = Field(None, description="Hostname")
    extras: Optional[str] = Field(None, description="Extra information")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class LanCableLabelRequest(BaseModel):
    from_id: str = Field(..., description="From DataMatrix ID")
    from_location: str = Field(..., description="From location")
    from_ip: str = Field(..., description="From IP")
    from_port: str = Field(..., description="From port")
    to_id: str = Field(..., description="To DataMatrix ID")
    to_location: str = Field(..., description="To location")
    to_ip: str = Field(..., description="To IP")
    to_port: str = Field(..., description="To port")
    connection_id: str = Field(..., description="Connection DataMatrix ID")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class TextHeaderLabelRequest(BaseModel):
    header_text: str = Field(..., description="Header text")
    content_text: str = Field(..., description="Body text")
    header_font_size: int = Field(30, gt=0, description="Header font size")
    content_font_size: int = Field(20, gt=0, description="Body font size")
    underline_thickness: int = Field(2, gt=0, description="Underline thickness")
    padding_mm: float = Field(2.0, gt=0, description="Padding in mm")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0)
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0)


class RawZplRequest(BaseModel):
    zpl: str = Field(..., description="Raw ZPL-II code")
    label_width_mm: float = Field(COMMON_LABEL_WIDTH, gt=0, description="Label width in mm")
    label_height_mm: float = Field(COMMON_LABEL_HEIGHT, gt=0, description="Label height in mm")


# --- Form dependencies ---

def _get_text_label_request(
    content: str = Form(..., description="Text to print"),
    font: str = Form(DEFAULT_FONT, description="ZPL font identifier"),
    font_size: int = Form(DEFAULT_FONT_SIZE, gt=1, description="Font size"),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0, description="Label width in mm"),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0, description="Label height in mm"),
) -> TextLabelRequest:
    return TextLabelRequest(
        content=content,
        font=font,
        font_size=font_size,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_qr_label_request(
    data: str = Form(..., description="QR payload"),
    qr_magnification: int = Form(4, gt=1, description="Module magnification"),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
    right_text: Optional[str] = Form(None, description="Text to the right"),
    bottom_text: Optional[str] = Form(None, description="Text below"),
    padding_px: int = Form(5, ge=0, description="Padding in px"),
) -> QRLabelRequest:
    return QRLabelRequest(
        data=data,
        qr_magnification=qr_magnification,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
        right_text=right_text,
        bottom_text=bottom_text,
        padding_px=padding_px,
    )


def _get_id_label_request(
    id_category: str = Form(..., description="Category code (e.g. 'NET')"),
    id_type: str = Form(..., description="Type code (e.g. 'SRV')"),
    module_ratio: int = Form(3, gt=0),
    padding_x: int = Form(5, ge=0),
    padding_y: int = Form(5, ge=0),
    print_date: bool = Form(True),
    date_override: Optional[str] = Form(None, description="Override date YYYY-MM-DD"),
    date_font_size: int = Form(10, gt=1),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> IdLabelRequest:
    return IdLabelRequest(
        id_category=id_category,
        id_type=id_type,
        module_ratio=module_ratio,
        padding_x=padding_x,
        padding_y=padding_y,
        print_date=print_date,
        date_override=date_override,
        date_font_size=date_font_size,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_cable_type_label_request(
    from_text: str = Form(...),
    to_text: str = Form(...),
    length_cm: float = Form(..., ge=0),
    spec_text: Optional[str] = Form(None),
    id_type: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> CableTypeLabelRequest:
    return CableTypeLabelRequest(
        from_text=from_text,
        to_text=to_text,
        length_cm=length_cm,
        spec_text=spec_text,
        id_type=id_type,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_cable_usage_label_request(
    from_text: str = Form(...),
    to_text: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> CableUsageLabelRequest:
    return CableUsageLabelRequest(
        from_text=from_text,
        to_text=to_text,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_container_label_request(
    content: str = Form(...),
    position: str = Form(...),
    id_category: str = Form(...),
    id_type: str = Form(...),
    module_ratio: int = Form(3, gt=0),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> ContainerLabelRequest:
    return ContainerLabelRequest(
        content=content,
        position=position,
        id_category=id_category,
        id_type=id_type,
        module_ratio=module_ratio,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_food_label_request(
    bbf_date: str = Form(...),
    food: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> FoodLabelRequest:
    return FoodLabelRequest(
        bbf_date=bbf_date,
        food=food,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_storage_device_label_request(
    size: str = Form(...),
    info: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> StorageDeviceLabelRequest:
    return StorageDeviceLabelRequest(
        size=size,
        info=info,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_pcb_label_request(
    project: str = Form(...),
    info: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> PcbLabelRequest:
    return PcbLabelRequest(
        project=project,
        info=info,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_power_supply_label_request(
    volt: str = Form(...),
    acdc: str = Form(...),
    amps: str = Form(...),
    plug: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> PowerSupplyLabelRequest:
    return PowerSupplyLabelRequest(
        volt=volt,
        acdc=acdc,
        amps=amps,
        plug=plug,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_micro_controller_label_request(
    mcu_type: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> MicroControllerLabelRequest:
    return MicroControllerLabelRequest(
        mcu_type=mcu_type,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_network_device_label_request(
    device_id: str = Form(...),
    name: str = Form(...),
    location: str = Form(...),
    ip: str = Form(...),
    hostname: Optional[str] = Form(None),
    extras: Optional[str] = Form(None),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> NetworkDeviceLabelRequest:
    return NetworkDeviceLabelRequest(
        device_id=device_id,
        name=name,
        location=location,
        ip=ip,
        hostname=hostname,
        extras=extras,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_lan_cable_label_request(
    from_id: str = Form(...),
    from_location: str = Form(...),
    from_ip: str = Form(...),
    from_port: str = Form(...),
    to_id: str = Form(...),
    to_location: str = Form(...),
    to_ip: str = Form(...),
    to_port: str = Form(...),
    connection_id: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> LanCableLabelRequest:
    return LanCableLabelRequest(
        from_id=from_id,
        from_location=from_location,
        from_ip=from_ip,
        from_port=from_port,
        to_id=to_id,
        to_location=to_location,
        to_ip=to_ip,
        to_port=to_port,
        connection_id=connection_id,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_text_header_label_request(
    header_text: str = Form(...),
    content_text: str = Form(...),
    header_font_size: int = Form(30, gt=0),
    content_font_size: int = Form(20, gt=0),
    underline_thickness: int = Form(2, gt=0),
    padding_mm: float = Form(2.0, gt=0),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> TextHeaderLabelRequest:
    return TextHeaderLabelRequest(
        header_text=header_text,
        content_text=content_text,
        header_font_size=header_font_size,
        content_font_size=content_font_size,
        underline_thickness=underline_thickness,
        padding_mm=padding_mm,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


def _get_raw_zpl_request(
    zpl: str = Form(...),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
) -> RawZplRequest:
    return RawZplRequest(
        zpl=zpl,
        label_width_mm=label_width_mm,
        label_height_mm=label_height_mm,
    )


# --- Endpoints ---

@app.post(
    "/labels/text",
    summary="Create Text Label",
    description="Generate a ZPL-II text label. Every parameter is exposed individually in the form."
)
async def create_text_label(
    req: TextLabelRequest = Depends(_get_text_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = TextLabel(
            content=req.content,
            font=req.font,
            font_size=req.font_size,
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("TextLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/qr",
    summary="Create QR Label",
    description="Generate a ZPL-II QR code label with optional text to the right and/or below."
)
async def create_qr_label(
    req: QRLabelRequest = Depends(_get_qr_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = QRLabel(
            data=req.data,
            qr_magnification=req.qr_magnification,
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            right_text=req.right_text,
            bottom_text=req.bottom_text,
            padding_px=req.padding_px,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("QRLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/id",
    summary="Create ID Label",
    description="Generate a ZPL-II DataMatrix ID label with optional date; parameters have sensible defaults."
)
async def create_id_label(
    req: IdLabelRequest = Depends(_get_id_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = IdLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            id_category=req.id_category,
            id_type=req.id_type,
            module_ratio=req.module_ratio,
            padding_x=req.padding_x,
            padding_y=req.padding_y,
            print_date=req.print_date,
            date_override=req.date_override,
            date_font_size=req.date_font_size,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("IdLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/cable-type",
    summary="Create Cable Type Label",
    description="Generate a cable type label showing from, to, length, optional spec, and DataMatrix."
)
async def create_cable_type_label(
    req: CableTypeLabelRequest = Depends(_get_cable_type_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = CableTypeLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            from_text=req.from_text,
            to_text=req.to_text,
            length_cm=req.length_cm,
            spec_text=req.spec_text or "",
            type_abbr=req.id_type,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("CableTypeLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/cable-usage",
    summary="Create Cable Usage Label",
    description="Generate a cable usage label showing 'from' and 'to' text in two columns."
)
async def create_cable_usage_label(
    req: CableUsageLabelRequest = Depends(_get_cable_usage_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = CableUsageLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            from_text=req.from_text,
            to_text=req.to_text,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("CableUsageLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/container",
    summary="Create Container Label",
    description="Generate a container label with content text and bottom DataMatrix+position."
)
async def create_container_label(
    req: ContainerLabelRequest = Depends(_get_container_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = ContainerLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            content=req.content,
            position=req.position,
            id_category=req.id_category,
            id_type=req.id_type,
            module_ratio=req.module_ratio,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("ContainerLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/food",
    summary="Create Food Label",
    description="Generate a food label with BBF date, DataMatrix, and food description."
)
async def create_food_label(
    req: FoodLabelRequest = Depends(_get_food_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = FoodLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            bbf_date=req.bbf_date,
            food=req.food,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("FoodLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/storage-device",
    summary="Create Storage Device Label",
    description="Generate a storage device label with size, DataMatrix, and info."
)
async def create_storage_device_label(
    req: StorageDeviceLabelRequest = Depends(_get_storage_device_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = StorageDeviceLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            size=req.size,
            info=req.info,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("StorageDeviceLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/pcb",
    summary="Create PCB Label",
    description="Generate a PCB label with DataMatrix, project, timestamp, and info."
)
async def create_pcb_label(
    req: PcbLabelRequest = Depends(_get_pcb_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = PcbLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            project=req.project,
            info=req.info,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("PcbLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/power-supply",
    summary="Create Power Supply Label",
    description="Generate a power supply label with voltage, AC/DC, amperage, plug, and DataMatrix."
)
async def create_power_supply_label(
    req: PowerSupplyLabelRequest = Depends(_get_power_supply_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = PowerSupplyLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            volt=req.volt,
            acdc=req.acdc,
            amps=req.amps,
            plug=req.plug,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("PowerSupplyLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/micro-controller",
    summary="Create Microcontroller Label",
    description="Generate a microcontroller label with DataMatrix and MCU type text."
)
async def create_micro_controller_label(
    req: MicroControllerLabelRequest = Depends(_get_micro_controller_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = MicroControllerLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            mcu_type=req.mcu_type,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("MicroControllerLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/network-device",
    summary="Create Network Device Label",
    description="Generate a network device label with DataMatrix and device details."
)
async def create_network_device_label(
    req: NetworkDeviceLabelRequest = Depends(_get_network_device_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = NetworkDeviceLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            device_id=req.device_id,
            name=req.name,
            location=req.location,
            ip=req.ip,
            hostname=req.hostname or "",
            extras=req.extras or "",
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("NetworkDeviceLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/lan-cable",
    summary="Create LAN Cable Label",
    description="Generate a LAN cable label showing 'from' and 'to' sections plus connection DataMatrix."
)
async def create_lan_cable_label(
    req: LanCableLabelRequest = Depends(_get_lan_cable_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = LanCableLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            from_id=req.from_id,
            from_location=req.from_location,
            from_ip=req.from_ip,
            from_port=req.from_port,
            to_id=req.to_id,
            to_location=req.to_location,
            to_ip=req.to_ip,
            to_port=req.to_port,
            connection_id=req.connection_id,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("LanCableLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/text-header",
    summary="Create Text Header Label",
    description="Generate a header/body label with underline."
)
async def create_text_header_label(
    req: TextHeaderLabelRequest = Depends(_get_text_header_label_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        preset = TextHeaderLabel(
            label_width_mm=req.label_width_mm,
            label_height_mm=req.label_height_mm,
            header_text=req.header_text,
            content_text=req.content_text,
            header_font_size=req.header_font_size,
            content_font_size=req.content_font_size,
            underline_thickness=req.underline_thickness,
            padding_mm=req.padding_mm,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("TextHeaderLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/image",
    summary="Create Image Label",
    description="Generate a label containing a centered image (JPEG/PNG)."
)
async def create_image_label(
    file: UploadFile = File(..., description="Image file (JPEG/PNG)"),
    label_width_mm: float = Form(COMMON_LABEL_WIDTH, gt=0),
    label_height_mm: float = Form(COMMON_LABEL_HEIGHT, gt=0),
    image_width_mm: Optional[float] = Form(None, gt=0),
    image_height_mm: Optional[float] = Form(None, gt=0),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix="." + file.filename.split(".")[-1])
        with tmp as buffer:
            shutil.copyfileobj(file.file, buffer)
        preset = ImageLabel(
            file_path=tmp.name,
            label_width_mm=label_width_mm,
            label_height_mm=label_height_mm,
            image_width_mm=image_width_mm,
            image_height_mm=image_height_mm,
        )
        zpl = preset.create_zpl()
        return _handle_output(zpl, label_width_mm, label_height_mm, preview)
    except Exception as e:
        logger.error("ImageLabel error: %s", e)
        raise HTTPException(400, str(e))


@app.post(
    "/labels/zpl",
    summary="Send Raw ZPL",
    description="Send raw ZPL-II code for preview or printing."
)
async def raw_zpl(
    req: RawZplRequest = Depends(_get_raw_zpl_request),
    preview: bool = Query(False, description="If true, only return PNG preview, don't print")
):
    try:
        return _handle_output(req.zpl, req.label_width_mm, req.label_height_mm, preview)
    except Exception as e:
        logger.error("Raw ZPL error: %s", e)
        raise HTTPException(400, str(e))


@app.get(
    "/categories",
    summary="Get Categories",
    description="Retrieve category and type definitions from categories.yml via IdFactory."
)
async def get_categories():
    factory = IdFactory("categories.yml")
    return factory.data
