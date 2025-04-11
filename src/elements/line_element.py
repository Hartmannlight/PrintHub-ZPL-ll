import logging
from src.elements.elements import Element

logger = logging.getLogger(__name__)


class LineElement(Element):
    """
    Represents a line element in a label.
    """

    def __init__(self, x1: int, y1: int, x2: int, y2: int, thickness: int = 3) -> None:
        """
        Initialize a LineElement.

        :param x1: Starting x-coordinate.
        :param y1: Starting y-coordinate.
        :param x2: Ending x-coordinate.
        :param y2: Ending y-coordinate.
        :param thickness: Line thickness.
        """
        logger.debug("Creating LineElement from (%d, %d) to (%d, %d) with thickness=%d",
                     x1, y1, x2, y2, thickness)
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2
        self.thickness = thickness

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the line element to its corresponding ZPL code.

        :param label: The parent label.
        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :return: ZPL code as a string.
        """
        new_x1 = self.x1 + offset_x
        new_y1 = self.y1 + offset_y
        new_x2 = self.x2 + offset_x
        new_y2 = self.y2 + offset_y

        start_x = max(new_x1, 0)
        start_y = max(new_y1, 0)
        width = max(new_x2 - start_x, 0) if self.x2 != self.x1 else self.thickness
        height = max(new_y2 - start_y, 0) if self.y2 != self.y1 else self.thickness
        zpl_code = f"^FO{start_x},{start_y}^GB{width},{height},{self.thickness}^FS"
        logger.debug("LineElement ZPL: %s", zpl_code)
        return zpl_code
