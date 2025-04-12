"""
NetworkDeviceLabel preset.

Creates a label with two main columns:
  - Column A (3/16 of label width) contains a centered DataMatrix element displaying a device ID.
    The device ID must be a valid ID from the NET category.
  - Column B (the remaining width) is subdivided into three rows:
      - Row 0: A nested 2x1 grid for the device name (left cell) and location (right cell).
      - Row 1: A nested 2x1 grid for the device IP (left cell) and hostname (right cell).
      - Row 2: A text element displaying extras.
"""

import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.data_matrix_element import DataMatrixElement
from src.elements.text_element import TextElement

logger = logging.getLogger(__name__)

class NetworkDeviceLabel(BaseLabelPreset):
    """
    Network Device Label preset.

    This preset creates a label with two main columns:
      - Column A (3/16 of the label width) contains a centered DataMatrix element displaying
        the device ID (which must be from the NET category).
      - Column B (the remaining width) is subdivided vertically into three rows:
          - Row 0: A nested grid (2 columns x 1 row) that displays the device name and location.
          - Row 1: A nested grid (2 columns x 1 row) that displays the device IP and hostname.
          - Row 2: A text element that displays extra information.
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, device_id: str,
                 name: str, location: str, ip: str, hostname: str, extras: str) -> None:
        """
        Initialize the NetworkDeviceLabel.

        :param label_width_mm: Overall label width in millimeters.
        :param label_height_mm: Overall label height in millimeters.
        :param device_id: Device ID (must be a valid NET ID).
        :param name: Device name.
        :param location: Device location.
        :param ip: Device IP address.
        :param hostname: Device hostname.
        :param extras: Additional information.
        """
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
        Generate ZPL code for the NetworkDeviceLabel.

        :return: A string containing the complete ZPL code.
        """
        # Calculate the column widths.
        col_a_width = self.label_width_mm * 3 / 16
        col_b_width = self.label_width_mm - col_a_width

        # Create the main grid (2 columns x 1 row).
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width, height_mm=self.label_height_mm)

        # Column A: Add a centered DataMatrix element with the device ID.
        # The device ID must be a valid NET ID.
        data_matrix = DataMatrixElement.from_id(
            self.device_id,
            module_ratio=4,
            center_horizontal=True,
            center_vertical=True
        )
        main_grid.cell(0, 0).add_element(data_matrix)

        # Column B: Create a nested grid with 1 column and 3 rows.
        grid_b = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=3,
            draw_grid_lines=True
        )
        row_height_b = self.label_height_mm / 3
        for row in range(3):
            grid_b.set_cell_size(0, row, width_mm=col_b_width, height_mm=row_height_b)

        # Row 0: Nested grid 2x1 for name and location.
        grid_b0 = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=row_height_b,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        half_width_b = col_b_width / 2
        grid_b0.set_cell_size(0, 0, width_mm=half_width_b, height_mm=row_height_b)
        grid_b0.set_cell_size(1, 0, width_mm=half_width_b, height_mm=row_height_b)
        grid_b0.cell(0, 0).add_element(TextElement(text=self.name, center_horizontal=True, center_vertical=True))
        grid_b0.cell(1, 0).add_element(TextElement(text=self.location, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 0).add_element(GridElement(grid_b0))

        # Row 1: Nested grid 2x1 for IP and hostname.
        grid_b1 = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=row_height_b,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        grid_b1.set_cell_size(0, 0, width_mm=half_width_b, height_mm=row_height_b)
        grid_b1.set_cell_size(1, 0, width_mm=half_width_b, height_mm=row_height_b)
        grid_b1.cell(0, 0).add_element(TextElement(text=self.ip, center_horizontal=True, center_vertical=True))
        grid_b1.cell(1, 0).add_element(TextElement(text=self.hostname, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 1).add_element(GridElement(grid_b1))

        # Row 2: Add a TextElement for extras.
        grid_b.cell(0, 2).add_element(TextElement(text=self.extras, center_horizontal=True, center_vertical=True))

        # Add the nested Column B grid to the main grid.
        main_grid.cell(1, 0).add_element(GridElement(grid_b))

        return main_grid.create()
