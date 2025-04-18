# src/presets/micro_controller_label.py
import logging
from src.presets.base_label import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.utils.label_helpers import make_datamatrix
from src.elements.text_element import TextElement

logger = logging.getLogger(__name__)


class MicroControllerLabel(BaseLabelPreset):
    """
    Preset for microcontroller labels:
      - DataMatrix with timestamp → hex
      - MCU type text
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, mcu_type: str) -> None:
        """
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :param mcu_type: Microcontroller type string
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing MicroControllerLabel(width=%.1f, height=%.1f, mcu_type=%r)",
                     label_width_mm, label_height_mm, mcu_type)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.mcu_type = mcu_type

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the microcontroller label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for MicroControllerLabel")
        # Main grid: 3 cols
        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=3, rows=1)
        main.set_cell_size(0, 0, width_mm=4.0, height_mm=self.label_height_mm)
        main.set_cell_size(1, 0, width_mm=20.0, height_mm=self.label_height_mm)
        main.set_cell_size(2, 0, width_mm=self.label_width_mm - 24.0, height_mm=self.label_height_mm)

        # Column B: nested 2 rows
        grid_b = GridLabel(real_width_mm=20.0, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        grid_b.set_cell_size(0, 0, width_mm=20.0, height_mm=10.0)
        grid_b.set_cell_size(0, 1, width_mm=20.0, height_mm=self.label_height_mm - 10.0)

        # Top half: nested 2 cols
        grid_b0 = GridLabel(real_width_mm=20.0, real_height_mm=20.0, cols=1, rows=2, draw_grid_lines=True)
        grid_b0.set_cell_size(0, 0, width_mm=20.0, height_mm=10.0)
        grid_b0.set_cell_size(0, 1, width_mm=20.0, height_mm=10.0)
        grid_b00 = GridLabel(real_width_mm=20.0, real_height_mm=10.0, cols=2, rows=1, draw_grid_lines=True)
        grid_b00.set_cell_size(0, 0, width_mm=10.0, height_mm=10.0)
        grid_b00.set_cell_size(1, 0, width_mm=10.0, height_mm=10.0)

        dm = make_datamatrix("BTL", "MCU")
        ts = dm.data.split("-")[2]
        hex_str = format(int(ts[-5:]), 'X') if ts.isdigit() else ""

        grid_b00.cell(0, 0).add_element(dm)
        grid_b00.cell(1, 0).add_element(TextElement(text=hex_str, center_horizontal=True, center_vertical=True))

        grid_b0.cell(0, 0).add_element(GridElement(grid_b00))
        grid_b0.cell(0, 1).add_element(TextElement(text=self.mcu_type, center_horizontal=True, center_vertical=True))

        grid_b.cell(0, 0).add_element(GridElement(grid_b0))
        main.cell(1, 0).add_element(GridElement(grid_b))

        return main.create()
