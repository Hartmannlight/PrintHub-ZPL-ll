# src/presets/cable_type_label.py
import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.line_element import LineElement
from src.utils.conversion import mm_to_pixels
from src.utils.label_helpers import make_datamatrix

logger = logging.getLogger(__name__)


class CableTypeLabel(BaseLabelPreset):
    """
    Preset for cable type labels:
      - Left block: From, To, Length
      - Center: dividing line
      - Right block: Spec text + DataMatrix code
    """

    COL_B_WIDTH_MM: float = 20.0
    LINE_THICKNESS: int = 2
    DRAW_GRID_LINES: bool = True

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        from_text: str,
        to_text: str,
        length_cm: float,
        spec_text: str,
        type_abbr: str,
    ) -> None:
        """
        :param label_width_mm: Label width in mm (>0)
        :param label_height_mm: Label height in mm (>0)
        :param from_text: Text for the "from" field
        :param to_text: Text for the "to" field
        :param length_cm: Cable length in cm
        :param spec_text: Specification text
        :param type_abbr: Cable type abbreviation (e.g. 'NTZW')
        :raises ValueError: If dimensions are not positive
        """
        logger.debug(
            "Initializing CableTypeLabel(width=%.1f, height=%.1f, type=%s)",
            label_width_mm, label_height_mm, type_abbr,
        )
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_text = from_text
        self.to_text = to_text
        self.length_cm = length_cm
        self.spec_text = spec_text
        self.type_abbr = type_abbr

    def create_zpl(self) -> str:
        """
        Build and return the ZPL for this cable-type label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for CableTypeLabel")

        # Compute column widths
        col_a = (self.label_width_mm - self.COL_B_WIDTH_MM) / 2
        col_b = self.COL_B_WIDTH_MM
        col_c = col_a

        # Main grid (3 cols × 1 row)
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=3,
            rows=1,
            draw_grid_lines=self.DRAW_GRID_LINES,
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b, height_mm=self.label_height_mm)
        main_grid.set_cell_size(2, 0, width_mm=col_c, height_mm=self.label_height_mm)

        # Column A: nested grid 1×3 for From/To/Length
        grid_a = GridLabel(real_width_mm=col_a, real_height_mm=self.label_height_mm, cols=1, rows=3, draw_grid_lines=self.DRAW_GRID_LINES)
        row_h = self.label_height_mm / 3
        for row in range(3):
            grid_a.set_cell_size(0, row, width_mm=col_a, height_mm=row_h)
        grid_a.cell(0, 0).add_element(TextElement(text=self.from_text, center_horizontal=True, center_vertical=True))
        grid_a.cell(0, 1).add_element(TextElement(text=self.to_text, center_horizontal=True, center_vertical=True))
        grid_a.cell(0, 2).add_element(TextElement(text=f"{self.length_cm} cm", center_horizontal=True, center_vertical=True))
        main_grid.cell(0, 0).add_element(GridElement(grid_a))

        # Column B: vertical line
        px_b = mm_to_pixels(col_b)
        px_h = mm_to_pixels(self.label_height_mm)
        center_x = px_b // 2
        main_grid.cell(1, 0).add_element(LineElement(x1=center_x, y1=0, x2=center_x, y2=px_h, thickness=self.LINE_THICKNESS))

        # Column C: spec + DataMatrix
        grid_c = GridLabel(real_width_mm=col_c, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=self.DRAW_GRID_LINES)
        top_h = self.label_height_mm * 2 / 3
        bot_h = self.label_height_mm - top_h
        grid_c.set_cell_size(0, 0, width_mm=col_c, height_mm=top_h)
        grid_c.set_cell_size(0, 1, width_mm=col_c, height_mm=bot_h)
        grid_c.cell(0, 0).add_element(TextElement(text=self.spec_text, center_horizontal=True, center_vertical=True))
        grid_c.cell(0, 1).add_element(make_datamatrix("KAB", self.type_abbr, module_ratio=3))
        main_grid.cell(2, 0).add_element(GridElement(grid_c))

        zpl = main_grid.create()
        logger.debug("Generated ZPL length=%d", len(zpl))
        return zpl
