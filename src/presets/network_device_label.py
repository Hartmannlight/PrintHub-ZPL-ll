# src/presets/network_device_label.py
import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.data_matrix_element import DataMatrixElement
from src.elements.text_element import TextElement

logger = logging.getLogger(__name__)


class NetworkDeviceLabel(BaseLabelPreset):
    """
    Preset for network device labels:
      - Col A: DataMatrix with device ID
      - Col B: 3 rows → name/location, IP/hostname, extras
    """

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        device_id: str,
        name: str,
        location: str,
        ip: str,
        hostname: str,
        extras: str,
    ) -> None:
        """
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :param device_id: Valid NET category ID
        :param name: Device name
        :param location: Device location
        :param ip: Device IP
        :param hostname: Device hostname
        :param extras: Additional info
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing NetworkDeviceLabel(width=%.1f, height=%.1f, device_id=%r)",
                     label_width_mm, label_height_mm, device_id)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.device_id = device_id
        self.name = name
        self.location = location
        self.ip = ip
        self.hostname = hostname
        self.extras = extras

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the network device label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for NetworkDeviceLabel")
        col_a = self.label_width_mm * 3 / 16
        col_b = self.label_width_mm - col_a

        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=2, rows=1, draw_grid_lines=True)
        main.set_cell_size(0, 0, width_mm=col_a, height_mm=self.label_height_mm)
        main.set_cell_size(1, 0, width_mm=col_b, height_mm=self.label_height_mm)

        # Column A
        dm = DataMatrixElement.from_id(self.device_id, module_ratio=4, center_horizontal=True, center_vertical=True)
        main.cell(0, 0).add_element(dm)

        # Column B
        grid_b = GridLabel(real_width_mm=col_b, real_height_mm=self.label_height_mm, cols=1, rows=3, draw_grid_lines=True)
        row_h = self.label_height_mm / 3
        for r in range(3):
            grid_b.set_cell_size(0, r, width_mm=col_b, height_mm=row_h)

        # Row 0: name/location
        sub0 = GridLabel(real_width_mm=col_b, real_height_mm=row_h, cols=2, rows=1, draw_grid_lines=True)
        half = col_b / 2
        sub0.set_cell_size(0, 0, width_mm=half, height_mm=row_h)
        sub0.set_cell_size(1, 0, width_mm=half, height_mm=row_h)
        sub0.cell(0, 0).add_element(TextElement(text=self.name, center_horizontal=True, center_vertical=True))
        sub0.cell(1, 0).add_element(TextElement(text=self.location, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 0).add_element(GridElement(sub0))

        # Row 1: IP/hostname
        sub1 = GridLabel(real_width_mm=col_b, real_height_mm=row_h, cols=2, rows=1, draw_grid_lines=True)
        sub1.set_cell_size(0, 0, width_mm=half, height_mm=row_h)
        sub1.set_cell_size(1, 0, width_mm=half, height_mm=row_h)
        sub1.cell(0, 0).add_element(TextElement(text=self.ip, center_horizontal=True, center_vertical=True))
        sub1.cell(1, 0).add_element(TextElement(text=self.hostname, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 1).add_element(GridElement(sub1))

        # Row 2: extras
        grid_b.cell(0, 2).add_element(TextElement(text=self.extras, center_horizontal=True, center_vertical=True))

        main.cell(1, 0).add_element(GridElement(grid_b))
        return main.create()
