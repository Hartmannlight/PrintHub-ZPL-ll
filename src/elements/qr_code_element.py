import logging
from src.elements.elements import Element

logger = logging.getLogger(__name__)

class QRCodeElement(Element):
    """
    Represents a QR Code element in a label.

    Measures its rendered size via ZPLElementMeasurer so centering is exact.
    """

    def __init__(
        self,
        data: str,
        x: int = 0,
        y: int = 0,
        model: int = 2,
        magnification: int = 4,
        center_horizontal: bool = False,
        center_vertical: bool = False,
    ) -> None:
        """
        :param data: The data to encode.
        :param x: X-coordinate offset in pixels.
        :param y: Y-coordinate offset in pixels.
        :param model: QR code model (1 or 2).
        :param magnification: Module magnification factor.
        :param center_horizontal: Center horizontally if True.
        :param center_vertical: Center vertically if True.
        """
        self.data = data
        self.x = x
        self.y = y
        self.model = model
        self.magnification = magnification
        self.center_horizontal = center_horizontal
        self.center_vertical = center_vertical

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the QR Code element to its corresponding ZPL code,
        measuring actual size for exact centering.

        :param label: The parent label.
        :param offset_x: Horizontal offset (px).
        :param offset_y: Vertical offset (px).
        :return: ZPL code as a string.
        """
        # Build a standalone snippet to measure real rendered size
        snippet = (
            f"^XA"
            f"^FO0,0"
            f"^BQN,{self.model},{self.magnification}"
            f"^FDLA,{self.data}"
            f"^FS"
            f"^XZ"
        )
        measurer = label.measurer
        qr_width, qr_height, _ = measurer.measure_zpl(snippet)

        # Compute final position
        final_x = self.x
        final_y = self.y
        if self.center_horizontal:
            final_x = int((label.width_px - qr_width) / 2 + self.x)
        if self.center_vertical:
            final_y = int((label.height_px - qr_height) / 2 + self.y)

        final_x = max(final_x + offset_x, 0)
        final_y = max(final_y + offset_y, 0)

        # Emit the actual QR ZPL
        zpl_code = (
            f"^FO{final_x},{final_y}"
            f"^BQN,{self.model},{self.magnification}"
            f"^FDLA,{self.data}"
            f"^FS"
        )
        logger.debug("QRCodeElement ZPL: %s", zpl_code)
        return zpl_code
