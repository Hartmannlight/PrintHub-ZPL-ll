# src/presets/food_label.py
import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.utils.label_helpers import make_datamatrix

logger = logging.getLogger(__name__)


class FoodLabel(BaseLabelPreset):
    """
    Preset for food labels:
      - Column A: BBF date + DataMatrix
      - Column B: food info text
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, bbf_date: str, food: str) -> None:
        """
        :param label_width_mm: Label width in mm (>0)
        :param label_height_mm: Label height in mm (>0)
        :param bbf_date: Best-before date
        :param food: Food description
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing FoodLabel(width=%.1f, height=%.1f, bbf_date=%r, food=%r)",
                     label_width_mm, label_height_mm, bbf_date, food)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.bbf_date = bbf_date
        self.food = food

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the food label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for FoodLabel")
        col_a = self.label_width_mm / 3
        col_b = self.label_width_mm - col_a

        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=2, rows=1, draw_grid_lines=True)
        main.set_cell_size(0, 0, width_mm=col_a, height_mm=self.label_height_mm)
        main.set_cell_size(1, 0, width_mm=col_b, height_mm=self.label_height_mm)

        grid_a = GridLabel(real_width_mm=col_a, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        row_h = self.label_height_mm / 2
        grid_a.set_cell_size(0, 0, width_mm=col_a, height_mm=row_h)
        grid_a.set_cell_size(0, 1, width_mm=col_a, height_mm=row_h)
        grid_a.cell(0, 0).add_element(TextElement(text=self.bbf_date, center_horizontal=True, center_vertical=True))
        grid_a.cell(0, 1).add_element(make_datamatrix("VBM", "ESS", module_ratio=3))
        main.cell(0, 0).add_element(GridElement(grid_a))

        main.cell(1, 0).add_element(TextElement(text=self.food, center_horizontal=True, center_vertical=True))
        return main.create()
