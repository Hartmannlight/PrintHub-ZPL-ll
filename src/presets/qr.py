# src/presets/qr.py
import logging
from src.presets.base import BaseLabelPreset
from src.elements.qr_code_element import QRCodeElement
from src.label import Label

logger = logging.getLogger(__name__)


class QRLabel(BaseLabelPreset):
    """
    Preset for QR code labels: centers a QR code on the label.
    """

    def __init__(self, data: str, qr_magnification: int = 4, label_width_mm: float = 70, label_height_mm: float = 100) -> None:
        """
        :param data: Data to encode
        :param qr_magnification: Magnification factor
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing QRLabel(data=%r, mag=%d, width=%.1f, height=%.1f)", data, qr_magnification, label_width_mm, label_height_mm)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.data = data
        self.qr_magnification = qr_magnification
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the QR label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for QRLabel")
        qr_elem = QRCodeElement(
            data=self.data,
            x=0,
            y=0,
            model=2,
            magnification=self.qr_magnification,
            center_horizontal=True,
            center_vertical=True,
        )
        return Label(qr_elem, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl
