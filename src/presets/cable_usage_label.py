# src/presets/cable_usage_label.py
import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement

logger = logging.getLogger(__name__)


class CableUsageLabel(BaseLabelPreset):
    """
    Preset for cable usage labels:
      - Two columns (From / To), each with 2 rows of identical text.
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, from_text: str, to_text: str) -> None:
        """
        :param label_width_mm: Label width in mm (>0)
        :param label_height_mm: Label height in mm (>0)
        :param from_text: Text for left column
        :param to_text: Text for right column
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing CableUsageLabel(width=%.1f, height=%.1f)", label_width_mm, label_height_mm)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_text = from_text
        self.to_text = to_text

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the cable usage label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for CableUsageLabel")
        column_w = self.label_width_mm / 2
        row_h = self.label_height_mm / 2

        # Left column
        grid_from = GridLabel(real_width_mm=column_w, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        for r in range(2):
            grid_from.set_cell_size(0, r, width_mm=column_w, height_mm=row_h)
            grid_from.cell(0, r).add_element(TextElement(text=self.from_text, center_horizontal=True, center_vertical=True))

        # Right column
        grid_to = GridLabel(real_width_mm=column_w, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        for r in range(2):
            grid_to.set_cell_size(0, r, width_mm=column_w, height_mm=row_h)
            grid_to.cell(0, r).add_element(TextElement(text=self.to_text, center_horizontal=True, center_vertical=True))

        # Main grid
        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=2, rows=1, draw_grid_lines=True)
        main.set_cell_size(0, 0, width_mm=column_w, height_mm=self.label_height_mm)
        main.set_cell_size(1, 0, width_mm=column_w, height_mm=self.label_height_mm)
        main.cell(0, 0).add_element(GridElement(grid_from))
        main.cell(1, 0).add_element(GridElement(grid_to))

        return main.create()
