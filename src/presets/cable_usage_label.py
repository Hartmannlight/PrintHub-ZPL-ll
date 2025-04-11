import logging
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.elements.line_element import LineElement
from src.config import DPI
from src.utils.conversion import mm_to_pixels
from src.presets.base import BaseLabelPreset


class CableUsageLabel(BaseLabelPreset):
    """
    Cable Usage Label preset.

    Creates a label with two sections (left and right), each composed of a nested grid with 5 rows.
    The bottom row displays the connection_id, and the right section shows the to_id as a DataMatrix in its top row.
    """
    NUM_ROWS = 5
    COL_B_WIDTH_MM = 20

    def __init__(self, label_width_mm: float, label_height_mm: float, from_text: str, to_text: str,
                 from_id: str, to_id: str, connection_id: str):
        """
        Initialize a CableUsageLabel.

        :param label_width_mm: Label width in mm.
        :param label_height_mm: Label height in mm.
        :param from_text: Text for the left section.
        :param to_text: Text for the right section.
        :param from_id: ID for the left section.
        :param to_id: ID for the right section.
        :param connection_id: Connection ID to display in both sections.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_text = from_text
        self.to_text = to_text
        self.from_id = from_id
        self.to_id = to_id
        self.connection_id = connection_id

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the cable usage label.

        :return: ZPL code as a string.
        """
        side_width_mm = (self.label_width_mm - self.COL_B_WIDTH_MM) / 2
        col_b_width_mm = self.COL_B_WIDTH_MM

        # Main grid: 3 columns x 1 row.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=3,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=side_width_mm, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width_mm, height_mm=self.label_height_mm)
        main_grid.set_cell_size(2, 0, width_mm=side_width_mm, height_mm=self.label_height_mm)

        # Left section
        grid_left = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=self.NUM_ROWS,
            draw_grid_lines=True
        )
        row_height_left = self.label_height_mm / self.NUM_ROWS
        for row in range(self.NUM_ROWS):
            grid_left.set_cell_size(0, row, width_mm=side_width_mm, height_mm=row_height_left)

        # Row 0: Nested grid for "From:" and from_id.
        grid_left_0 = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=row_height_left,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        col_left_0_width = side_width_mm / 2
        grid_left_0.set_cell_size(0, 0, width_mm=col_left_0_width, height_mm=row_height_left)
        grid_left_0.set_cell_size(1, 0, width_mm=col_left_0_width, height_mm=row_height_left)
        grid_left_0.cell(0, 0).add_element(TextElement(text="From:", center_horizontal=True, center_vertical=True))
        grid_left_0.cell(1, 0).add_element(DataMatrixElement(self.from_id))
        grid_left.cell(0, 0).add_element(GridElement(grid_left_0))

        # Rows 1-3: Display from_text.
        for row in range(1, 4):
            grid_left.cell(0, row).add_element(TextElement(text=self.from_text, center_horizontal=True, center_vertical=True))
        # Row 4: connection_id.
        grid_left.cell(0, 4).add_element(DataMatrixElement(self.connection_id))

        # Right section
        grid_right = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=self.NUM_ROWS,
            draw_grid_lines=True
        )
        row_height_right = self.label_height_mm / self.NUM_ROWS
        for row in range(self.NUM_ROWS):
            grid_right.set_cell_size(0, row, width_mm=side_width_mm, height_mm=row_height_right)

        # Row 0: Nested grid for "To:" and to_id.
        grid_right_0 = GridLabel(
            real_width_mm=side_width_mm,
            real_height_mm=row_height_right,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        col_right_0_width = side_width_mm / 2
        grid_right_0.set_cell_size(0, 0, width_mm=col_right_0_width, height_mm=row_height_right)
        grid_right_0.set_cell_size(1, 0, width_mm=col_right_0_width, height_mm=row_height_right)
        grid_right_0.cell(0, 0).add_element(TextElement(text="To:", center_horizontal=True, center_vertical=True))
        grid_right_0.cell(1, 0).add_element(DataMatrixElement(self.to_id))
        grid_right.cell(0, 0).add_element(GridElement(grid_right_0))

        # Rows 1-3: Display to_text.
        for row in range(1, 4):
            grid_right.cell(0, row).add_element(TextElement(text=self.to_text, center_horizontal=True, center_vertical=True))
        # Row 4: connection_id.
        grid_right.cell(0, 4).add_element(DataMatrixElement(self.connection_id))

        # Middle column (vertical divider)
        cell_width_b_px = mm_to_pixels(self.COL_B_WIDTH_MM, DPI)
        cell_height_b_px = mm_to_pixels(self.label_height_mm, DPI)
        divider_x = cell_width_b_px // 2
        line_element = LineElement(x1=divider_x, y1=0, x2=divider_x, y2=cell_height_b_px, thickness=2)

        # Assemble the main grid.
        main_grid.cell(0, 0).add_element(GridElement(grid_left))
        main_grid.cell(1, 0).add_element(line_element)
        main_grid.cell(2, 0).add_element(GridElement(grid_right))

        return main_grid.create()
