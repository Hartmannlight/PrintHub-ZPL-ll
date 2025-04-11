import logging
from typing import List
from src.elements.elements import Element
from src.config import DPI
from src.utils.zpl_element_measurer import ZPLElementMeasurer
from src.utils.conversion import mm_to_pixels

logger = logging.getLogger(__name__)


class GridCell:
    """
    Represents a virtual label cell in a grid.
    The first content added (or the first set_cell_size call) determines the cell's dimensions.
    """

    def __init__(self, col: int, row: int) -> None:
        """
        Initialize a GridCell.

        :param col: Column index.
        :param row: Row index.
        """
        self.col = col
        self.row = row
        self.elements: List[Element] = []
        self.cell_width_mm: float = None
        self.cell_height_mm: float = None

    def set_cell_size(self, width_mm: float, height_mm: float) -> None:
        """
        Set the cell dimensions in millimeters.

        :param width_mm: Cell width in mm.
        :param height_mm: Cell height in mm.
        """
        if self.cell_width_mm is None:
            self.cell_width_mm = width_mm
        else:
            if self.cell_width_mm != width_mm:
                logger.warning("Cell (%d, %d) width already set to %f mm; ignoring new width %f mm",
                               self.col, self.row, self.cell_width_mm, width_mm)
        if self.cell_height_mm is None:
            self.cell_height_mm = height_mm
        else:
            if self.cell_height_mm != height_mm:
                logger.warning("Cell (%d, %d) height already set to %f mm; ignoring new height %f mm",
                               self.col, self.row, self.cell_height_mm, height_mm)

    def add_element(self, element: Element, width_mm: float = None, height_mm: float = None) -> None:
        """
        Add an element to the cell, optionally setting cell dimensions if not already set.

        :param element: The element to add.
        :param width_mm: Optional cell width in mm.
        :param height_mm: Optional cell height in mm.
        """
        if self.cell_width_mm is None and width_mm is not None:
            self.cell_width_mm = width_mm
        if self.cell_height_mm is None and height_mm is not None:
            self.cell_height_mm = height_mm
        self.elements.append(element)

    def render(self, offset_x: int, offset_y: int, parent_dummy_label) -> str:
        """
        Render the cell content with an absolute offset.

        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :param parent_dummy_label: Dummy label used for centering elements.
        :return: ZPL code as a string.
        """
        cell_width_px = mm_to_pixels(self.cell_width_mm, DPI)
        cell_height_px = mm_to_pixels(self.cell_height_mm, DPI)
        dummy = type("DummyLabel", (), {})()
        dummy.width_px = cell_width_px
        dummy.height_px = cell_height_px
        dummy.measurer = ZPLElementMeasurer(width_px=cell_width_px, height_px=cell_height_px)

        zpl_parts = []
        for element in self.elements:
            zpl_parts.append(element.to_zpl(dummy, offset_x=offset_x, offset_y=offset_y))
        return "\n".join(zpl_parts)
