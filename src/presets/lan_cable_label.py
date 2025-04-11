import datetime
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.elements.line_element import LineElement
from src.config import DPI
from src.utils.conversion import mm_to_pixels


class LanCableLabel(BaseLabelPreset):
    """
    LAN Cable Label preset.

    Creates a label with two sides (left and right). The left side displays "From:" details,
    and the right side shows "To:" details. Both sides display the connection_id as a DataMatrix in the last row.
    Additionally, a nested grid on the top row of the right side displays the to_id as a DataMatrix.
    """
    NUM_ROWS = 5
    COL_B_WIDTH_MM = 20

    def __init__(self, label_width_mm: float, label_height_mm: float,
                 from_id: str, from_location: str, from_ip: str, from_port: str,
                 to_id: str, to_location: str, to_ip: str, to_port: str,
                 connection_id: str):
        """
        Initialize a LanCableLabel.

        :param label_width_mm: Label width in mm.
        :param label_height_mm: Label height in mm.
        :param from_id: ID for the "From:" section.
        :param from_location: Location for the "From:" section.
        :param from_ip: IP for the "From:" section.
        :param from_port: Port for the "From:" section.
        :param to_id: ID for the "To:" section.
        :param to_location: Location for the "To:" section.
        :param to_ip: IP for the "To:" section.
        :param to_port: Port for the "To:" section.
        :param connection_id: Connection ID to display.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_id = from_id
        self.from_location = from_location
        self.from_ip = from_ip
        self.from_port = from_port
        self.to_id = to_id
        self.to_location = to_location
        self.to_ip = to_ip
        self.to_port = to_port
        self.connection_id = connection_id

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the LAN cable label.

        :return: ZPL code as a string.
        """
        side_width_mm = (self.label_width_mm - self.COL_B_WIDTH_MM) / 2

        # Left section (From details)
        grid_a = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=self.NUM_ROWS,
            draw_grid_lines=True
        )
        row_height_a = self.label_height_mm / self.NUM_ROWS
        for row in range(self.NUM_ROWS):
            grid_a.set_cell_size(0, row, width_mm=side_width_mm, height_mm=row_height_a)

        # Row 0: Nested grid for "From:" and from_id.
        grid_a0 = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=row_height_a,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        col_a0_width = side_width_mm / 2
        grid_a0.set_cell_size(0, 0, width_mm=col_a0_width, height_mm=row_height_a)
        grid_a0.set_cell_size(1, 0, width_mm=col_a0_width, height_mm=row_height_a)
        grid_a0.cell(0, 0).add_element(TextElement(text="From:", center_horizontal=True, center_vertical=True))
        grid_a0.cell(1, 0).add_element(DataMatrixElement(self.from_id, validate_existing=True,
                                                          center_vertical=True, center_horizontal=True))
        grid_a.cell(0, 0).add_element(GridElement(grid_a0))

        # Row 1: from_location.
        grid_a.cell(0, 1).add_element(TextElement(text=self.from_location, center_horizontal=True, center_vertical=True))
        # Row 2: from_ip.
        grid_a.cell(0, 2).add_element(TextElement(text=self.from_ip, center_horizontal=True, center_vertical=True))
        # Row 3: from_port.
        grid_a.cell(0, 3).add_element(TextElement(text=self.from_port, center_horizontal=True, center_vertical=True))
        # Row 4: connection_id.
        grid_a.cell(0, 4).add_element(DataMatrixElement(self.connection_id, validate_existing=True,
                                                          center_vertical=True, center_horizontal=True))

        # Right section (To details)
        grid_c = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=self.NUM_ROWS,
            draw_grid_lines=True
        )
        row_height_c = self.label_height_mm / self.NUM_ROWS
        for row in range(self.NUM_ROWS):
            grid_c.set_cell_size(0, row, width_mm=side_width_mm, height_mm=row_height_c)

        # Row 0: Nested grid for "To:" and to_id.
        grid_c0 = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=row_height_c,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        col_c0_width = side_width_mm / 2
        grid_c0.set_cell_size(0, 0, width_mm=col_c0_width, height_mm=row_height_c)
        grid_c0.set_cell_size(1, 0, width_mm=col_c0_width, height_mm=row_height_c)
        grid_c0.cell(0, 0).add_element(TextElement(text="To:", center_horizontal=True, center_vertical=True))
        grid_c0.cell(1, 0).add_element(DataMatrixElement(self.to_id, validate_existing=True,
                                                          center_vertical=True, center_horizontal=True))
        grid_c.cell(0, 0).add_element(GridElement(grid_c0))

        # Row 1: to_location.
        grid_c.cell(0, 1).add_element(TextElement(text=self.to_location, center_horizontal=True, center_vertical=True))
        # Row 2: to_ip.
        grid_c.cell(0, 2).add_element(TextElement(text=self.to_ip, center_horizontal=True, center_vertical=True))
        # Row 3: to_port.
        grid_c.cell(0, 3).add_element(TextElement(text=self.to_port, center_horizontal=True, center_vertical=True))
        # Row 4: connection_id.
        grid_c.cell(0, 4).add_element(DataMatrixElement(self.connection_id, validate_existing=True,
                                                          center_vertical=True, center_horizontal=True))

        # Middle column (vertical divider)
        cell_width_b_px = mm_to_pixels(self.COL_B_WIDTH_MM, DPI)
        cell_height_b_px = mm_to_pixels(self.label_height_mm, DPI)
        divider_x = cell_width_b_px // 2
        line_element = LineElement(x1=divider_x, y1=0, x2=divider_x, y2=cell_height_b_px, thickness=2)

        # Assemble the main grid.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=3,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=side_width_mm, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=self.COL_B_WIDTH_MM, height_mm=self.label_height_mm)
        main_grid.set_cell_size(2, 0, width_mm=side_width_mm, height_mm=self.label_height_mm)

        main_grid.cell(0, 0).add_element(GridElement(grid_a))
        main_grid.cell(1, 0).add_element(line_element)
        main_grid.cell(2, 0).add_element(GridElement(grid_c))

        return main_grid.create()
