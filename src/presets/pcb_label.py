# src/presets/pcb_label.py
import logging
from datetime import datetime
from src.presets.base_label import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.utils.label_helpers import make_datamatrix

logger = logging.getLogger(__name__)


class PcbLabel(BaseLabelPreset):
    """
    Preset for PCB labels:
      - Col A: DataMatrix ID for PCB
      - Col B: project + timestamp, then info text
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, project: str, info: str) -> None:
        """
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :param project: Project description
        :param info: Additional information
        :raises ValueError: If dimensions not positive
        """
        logger.debug("Initializing PcbLabel(width=%.1f, height=%.1f, project=%r)",
                     label_width_mm, label_height_mm, project)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.project = project
        self.info = info

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the PCB label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for PcbLabel")
        col_a = self.label_width_mm * 5 / 16
        col_b = self.label_width_mm - col_a

        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=2, rows=1, draw_grid_lines=True)
        main.set_cell_size(0, 0, width_mm=col_a, height_mm=self.label_height_mm)
        main.set_cell_size(1, 0, width_mm=col_b, height_mm=self.label_height_mm)

        # Column A
        dm = make_datamatrix("BTL", "PCB", module_ratio=4)
        main.cell(0, 0).add_element(dm)

        # Column B
        grid_b = GridLabel(real_width_mm=col_b, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        half_h = self.label_height_mm / 2
        grid_b.set_cell_size(0, 0, width_mm=col_b, height_mm=half_h)
        grid_b.set_cell_size(0, 1, width_mm=col_b, height_mm=half_h)

        sub = GridLabel(real_width_mm=col_b, real_height_mm=half_h, cols=2, rows=1, draw_grid_lines=True)
        w = col_b / 2
        sub.set_cell_size(0, 0, width_mm=w, height_mm=half_h)
        sub.set_cell_size(1, 0, width_mm=w, height_mm=half_h)
        sub.cell(0, 0).add_element(TextElement(text=self.project, center_horizontal=True, center_vertical=True))
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sub.cell(1, 0).add_element(TextElement(text=ts, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 0).add_element(GridElement(sub))

        grid_b.cell(0, 1).add_element(TextElement(text=self.info, center_horizontal=True, center_vertical=True))
        main.cell(1, 0).add_element(GridElement(grid_b))

        return main.create()
