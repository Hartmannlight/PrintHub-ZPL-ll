import logging
from typing import List
from src.elements.elements import Element
from src.utils.zpl_element_measurer import ZPLElementMeasurer
from src.config import DPI
from src.utils.conversion import mm_to_pixels

logger = logging.getLogger(__name__)


class Label:
    """
    Container for constructing a label.

    This class combines individual elements into a complete ZPL label.
    The label size is specified in millimeters and converted to pixels.
    """

    def __init__(self, *elements: Element, width_mm: float = 70, height_mm: float = 100,
                 offset_x: int = 0, offset_y: int = 0) -> None:
        """
        Initialize the label with elements and dimensions.

        :param elements: Elements to include in the label.
        :param width_mm: Label width in millimeters.
        :param height_mm: Label height in millimeters.
        :param offset_x: Horizontal offset for the label elements.
        :param offset_y: Vertical offset for the label elements.
        """
        logger.debug("Creating Label with width_mm=%s, height_mm=%s, offset_x=%s, offset_y=%s",
                     width_mm, height_mm, offset_x, offset_y)
        self.elements: List[Element] = list(elements)
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.width_px = mm_to_pixels(self.width_mm, DPI)
        self.height_px = mm_to_pixels(self.height_mm, DPI)
        self.offset_x = offset_x
        self.offset_y = offset_y
        self.measurer: ZPLElementMeasurer = ZPLElementMeasurer.default()
        self.zpl: str = self._render_label()

    def _render_label(self) -> str:
        """
        Combine the ZPL code of all elements to create the complete label.

        :return: A string containing the complete ZPL code.
        """
        logger.debug("Rendering label with %d element(s).", len(self.elements))
        zpl_parts = ["^XA"]
        for element in self.elements:
            element_zpl = element.to_zpl(self, offset_x=self.offset_x, offset_y=self.offset_y)
            logger.debug("Rendered element to ZPL: %s", element_zpl)
            zpl_parts.append(element_zpl)
        zpl_parts.append("^XZ")
        complete_zpl = "\n".join(zpl_parts)
        logger.debug("Complete generated ZPL: %s", complete_zpl)
        return complete_zpl
