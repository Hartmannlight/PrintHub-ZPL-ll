# src/presets/power_supply_label.py
import logging
from src.presets.base_label import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.utils.label_helpers import make_datamatrix

logger = logging.getLogger(__name__)


class PowerSupplyLabel(BaseLabelPreset):
    """
    Preset for power supply labels:
      - Col A: DataMatrix for power supply
      - Col B: voltage / AC/DC
      - Col C: amperage / plug
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, volt: str, acdc: str, amps: str, plug: str) -> None:
        """
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :param volt: Voltage text
        :param acdc: AC/DC text
        :param amps: Amperage text
        :param plug: Plug type text
        :raises ValueError: If dimensions not positive
        """
        logger.debug("Initializing PowerSupplyLabel(width=%.1f, height=%.1f)", label_width_mm, label_height_mm)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.volt = volt
        self.acdc = acdc
        self.amps = amps
        self.plug = plug

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the power supply label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for PowerSupplyLabel")
        col_a = self.label_width_mm * 3 / 16
        rem = self.label_width_mm - col_a
        col_b = rem / 2
        col_c = rem / 2

        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=3, rows=1, draw_grid_lines=True)
        main.set_cell_size(0, 0, width_mm=col_a, height_mm=self.label_height_mm)
        main.set_cell_size(1, 0, width_mm=col_b, height_mm=self.label_height_mm)
        main.set_cell_size(2, 0, width_mm=col_c, height_mm=self.label_height_mm)

        # Column A
        dm = make_datamatrix("ELE", "NETZ", module_ratio=3)
        main.cell(0, 0).add_element(dm)

        # Column B
        grid_b = GridLabel(real_width_mm=col_b, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        half_h = self.label_height_mm / 2
        grid_b.set_cell_size(0, 0, width_mm=col_b, height_mm=half_h)
        grid_b.set_cell_size(0, 1, width_mm=col_b, height_mm=half_h)
        grid_b.cell(0, 0).add_element(TextElement(text=self.volt, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 1).add_element(TextElement(text=self.acdc, center_horizontal=True, center_vertical=True))
        main.cell(1, 0).add_element(GridElement(grid_b))

        # Column C
        grid_c = GridLabel(real_width_mm=col_c, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        grid_c.set_cell_size(0, 0, width_mm=col_c, height_mm=half_h)
        grid_c.set_cell_size(0, 1, width_mm=col_c, height_mm=half_h)
        grid_c.cell(0, 0).add_element(TextElement(text=self.amps, center_horizontal=True, center_vertical=True))
        grid_c.cell(0, 1).add_element(TextElement(text=self.plug, center_horizontal=True, center_vertical=True))
        main.cell(2, 0).add_element(GridElement(grid_c))

        return main.create()
