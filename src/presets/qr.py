from src.label import Label
from src.elements.qr_code_element import QRCodeElement
from src.presets.base import BaseLabelPreset


class QRLabel(BaseLabelPreset):
    """
    QR Label preset.

    Creates a label containing a centered QR code.
    """

    def __init__(self, data: str, qr_magnification: int = 4, label_width_mm: float = 70, label_height_mm: float = 100) -> None:
        """
        Initialize a QRLabel.

        :param data: Data to encode in the QR code.
        :param qr_magnification: Magnification factor for the QR code.
        :param label_width_mm: Label width in mm.
        :param label_height_mm: Label height in mm.
        """
        self.data = data
        self.qr_magnification = qr_magnification
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the QR label.

        :return: ZPL code as a string.
        """
        qr_element = QRCodeElement(
            data=self.data,
            x=0,
            y=0,
            model=2,
            magnification=self.qr_magnification,
            center_horizontal=True,
            center_vertical=True
        )
        return Label(qr_element, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl
