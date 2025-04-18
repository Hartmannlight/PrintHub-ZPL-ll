# src/presets/qr.py
import logging

from src.presets.base_label import BaseLabelPreset
from src.elements.qr_code_element import QRCodeElement
from src.elements.text_element import TextElement
from src.label import Label
from src.utils.conversion import mm_to_pixels
from src.utils.zpl_element_measurer import ZPLElementMeasurer

logger = logging.getLogger(__name__)

class QRLabel(BaseLabelPreset):
    """
    Preset for QR code labels with optional text to the right and/or below.
    Positions and spacing are driven by measured pixel sizes of the QR and text,
    plus an adjustable padding in pixels (default 5px).
    """

    def __init__(
        self,
        data: str,
        qr_magnification: int = 4,
        label_width_mm: float = 70,
        label_height_mm: float = 100,
        right_text: str = None,
        bottom_text: str = None,
        padding_px: int = 5,
    ) -> None:
        """
        Initialize a new QRLabel.

        :param data: Payload for the QR code.
        :param qr_magnification: Magnification factor for QR modules.
        :param label_width_mm: Label width in mm (>0).
        :param label_height_mm: Label height in mm (>0).
        :param right_text: Optional text placed to the right of the QR.
        :param bottom_text: Optional text placed below the QR.
        :param padding_px: Pixel padding between QR and text.
        :raises ValueError: If label dimensions are not positive.
        """
        logger.debug(
            "Initializing QRLabel(data=%r, mag=%d, w=%.1f, h=%.1f, padding_px=%d)",
            data, qr_magnification, label_width_mm, label_height_mm, padding_px
        )
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.data = data
        self.qr_magnification = qr_magnification
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.right_text = right_text
        self.bottom_text = bottom_text
        self.padding_px = padding_px

    def create_zpl(self) -> str:
        """
        Build the ZPL for this QR label, placing optional texts based on
        dynamic measurements and padding.
        """
        logger.debug("Generating ZPL for QRLabel with data=%r", self.data)
        measurer = ZPLElementMeasurer.default()

        # Measure QR code: width, height, top padding (blank space)
        qr_snippet = (
            f"^XA"
            f"^FO0,0"
            f"^BQN,2,{self.qr_magnification}"
            f"^FDLA,{self.data}^FS"
            f"^XZ"
        )
        qr_w_px, qr_h_px, qr_top_px = measurer.measure_zpl(qr_snippet)
        logger.debug("Measured QR (px): width=%d, height=%d, top=%d", qr_w_px, qr_h_px, qr_top_px)

        # Convert label size to pixels
        label_w_px = mm_to_pixels(self.label_width_mm)
        label_h_px = mm_to_pixels(self.label_height_mm)

        elements = []

        # Determine QR origin
        qr_x = 0
        qr_y = 0
        if self.bottom_text and not self.right_text:
            qr_x = (label_w_px - qr_w_px) // 2
        if self.right_text and not self.bottom_text:
            qr_y = (label_h_px - qr_h_px) // 2

        # Add QR element
        elements.append(QRCodeElement(
            data=self.data,
            x=qr_x,
            y=qr_y,
            model=2,
            magnification=self.qr_magnification
        ))

        # Place right_text immediately to QR's right
        if self.right_text:
            txt_snip = f"^XA^FO0,0^A0,20^FD{self.right_text}^FS^XZ"
            txt_w_px, txt_h_px, _ = measurer.measure_zpl(txt_snip)
            txt_x = qr_x + qr_w_px + self.padding_px
            txt_y = qr_y + (qr_h_px - txt_h_px) // 2
            logger.debug("Placing right_text=%r at (%d, %d)", self.right_text, txt_x, txt_y)
            elements.append(TextElement(
                text=self.right_text,
                x=txt_x,
                y=txt_y
            ))

        # Place bottom_text immediately below QR's content
        if self.bottom_text:
            bot_snip = f"^XA^FO0,0^A0,20^FD{self.bottom_text}^FS^XZ"
            bot_w_px, bot_h_px, _ = measurer.measure_zpl(bot_snip)
            bot_x = (label_w_px - bot_w_px) // 2
            bot_y = qr_y + qr_top_px + qr_h_px + self.padding_px
            logger.debug("Placing bottom_text=%r at (%d, %d)", self.bottom_text, bot_x, bot_y)
            elements.append(TextElement(
                text=self.bottom_text,
                x=bot_x,
                y=bot_y
            ))

        # Combine into final label
        zpl = Label(
            *elements,
            width_mm=self.label_width_mm,
            height_mm=self.label_height_mm
        ).zpl
        logger.debug("Generated ZPL length=%d", len(zpl))
        return zpl
