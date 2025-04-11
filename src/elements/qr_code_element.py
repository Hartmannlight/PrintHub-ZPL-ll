import logging
from src.elements.elements import Element

logger = logging.getLogger(__name__)


class QRCodeElement(Element):
    """
    Represents a QR Code element in a label.
    """

    def __init__(self, data: str, x: int = 0, y: int = 0,
                 model: int = 2, magnification: int = 4,
                 center_horizontal: bool = False, center_vertical: bool = False) -> None:
        """
        Initialize a QRCodeElement.

        :param data: The data to encode.
        :param x: X-coordinate.
        :param y: Y-coordinate.
        :param model: QR code model.
        :param magnification: QR code magnification.
        :param center_horizontal: Flag to center horizontally.
        :param center_vertical: Flag to center vertically.
        """
        logger.debug("Creating QRCodeElement with data: %s", data)
        self.data = data
        self.x = x
        self.y = y
        self.model = model
        self.magnification = magnification
        self.center_horizontal = center_horizontal
        self.center_vertical = center_vertical
        self.size = self.magnification * 10

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the QR Code element to its corresponding ZPL code.

        :param label: The parent label.
        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :return: ZPL code as a string.
        """
        final_x = self.x
        final_y = self.y
        if self.center_horizontal:
            final_x = int((label.width_px - self.size) / 2 + self.x)
        if self.center_vertical:
            final_y = int((label.height_px - self.size) / 2 + self.y)
        final_x = max(final_x + offset_x, 0)
        final_y = max(final_y + offset_y, 0)
        zpl_code = f"^FO{final_x},{final_y}^BQN,{self.model},{self.magnification}^FDLA,{self.data}^FS"
        logger.debug("QRCodeElement ZPL: %s", zpl_code)
        return zpl_code
