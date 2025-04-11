import logging
from typing import Dict, Tuple
from src.config import DPI
from src.grids.grid_cell import GridCell
from src.utils.zpl_element_measurer import ZPLElementMeasurer
from src.utils.conversion import mm_to_pixels

logger = logging.getLogger(__name__)


class GridLabel:
    """
    Represents a grid of virtual labels on a physical label.
    """

    def __init__(self, real_width_mm: float, real_height_mm: float,
                 cols: int, rows: int, draw_grid_lines: bool = False) -> None:
        """
        Initialize a GridLabel.

        :param real_width_mm: Physical label width in mm.
        :param real_height_mm: Physical label height in mm.
        :param cols: Number of columns.
        :param rows: Number of rows.
        :param draw_grid_lines: Flag to draw grid lines.
        """
        self.real_width_mm = real_width_mm
        self.real_height_mm = real_height_mm
        self.cols = cols
        self.rows = rows
        self.draw_grid_lines = draw_grid_lines

        self.cells: Dict[Tuple[int, int], GridCell] = {}
        for row in range(rows):
            for col in range(cols):
                self.cells[(col, row)] = GridCell(col=col, row=row)

        self.column_widths: Dict[int, float] = {}
        self.row_heights: Dict[int, float] = {}
        self.next_cell_index = (0, 0)

        self.label_width_px = mm_to_pixels(real_width_mm, DPI)
        self.label_height_px = mm_to_pixels(real_height_mm, DPI)

        class DummyLabel:
            pass
        dummy = DummyLabel()
        dummy.width_px = self.label_width_px
        dummy.height_px = self.label_height_px
        dummy.measurer = ZPLElementMeasurer.default()
        self.dummy_label = dummy

    def cell(self, col: int, row: int) -> GridCell:
        """
        Get the GridCell at the specified coordinates.

        :param col: Column index.
        :param row: Row index.
        :return: The corresponding GridCell.
        :raises IndexError: If the cell indices are out of range.
        """
        if col < 0 or col >= self.cols or row < 0 or row >= self.rows:
            raise IndexError("Cell index out of range")
        return self.cells[(col, row)]

    def next_cell(self) -> GridCell:
        """
        Retrieve the next available GridCell.

        :return: The next GridCell.
        :raises IndexError: If all cells are filled.
        """
        col, row = self.next_cell_index
        if row >= self.rows:
            raise IndexError("All grid cells are already filled.")
        cell = self.cells[(col, row)]
        if col < self.cols - 1:
            self.next_cell_index = (col + 1, row)
        else:
            self.next_cell_index = (0, row + 1)
        return cell

    def set_cell_size(self, col: int, row: int, width_mm: float, height_mm: float) -> None:
        """
        Set the cell size for a specific cell.

        :param col: Column index.
        :param row: Row index.
        :param width_mm: Cell width in mm.
        :param height_mm: Cell height in mm.
        """
        cell = self.cell(col, row)
        cell.set_cell_size(width_mm, height_mm)
        if col not in self.column_widths:
            self.column_widths[col] = width_mm
        else:
            if self.column_widths[col] != width_mm:
                logger.warning("Column %d width already set to %f mm; ignoring new width %f mm", col, self.column_widths[col], width_mm)
        if row not in self.row_heights:
            self.row_heights[row] = height_mm
        else:
            if self.row_heights[row] != height_mm:
                logger.warning("Row %d height already set to %f mm; ignoring new height %f mm", row, self.row_heights[row], height_mm)

    def _calculate_cell_offsets(self) -> Dict[Tuple[int, int], Tuple[int, int]]:
        """
        Calculate the pixel offsets for each cell based on the defined cell sizes.

        :return: Dictionary mapping (col, row) to (offset_x, offset_y).
        """
        offsets = {}
        cumulative_x_mm = 0
        col_offsets = {}
        for col in range(self.cols):
            col_width = self.column_widths.get(col, 0)
            col_offsets[col] = cumulative_x_mm
            cumulative_x_mm += col_width
        cumulative_y_mm = 0
        row_offsets = {}
        for row in range(self.rows):
            row_height = self.row_heights.get(row, 0)
            row_offsets[row] = cumulative_y_mm
            cumulative_y_mm += row_height

        for row in range(self.rows):
            for col in range(self.cols):
                offset_x = mm_to_pixels(col_offsets.get(col, 0), DPI)
                offset_y = mm_to_pixels(row_offsets.get(row, 0), DPI)
                offsets[(col, row)] = (offset_x, offset_y)
        return offsets

    def validate_grid(self) -> None:
        """
        Validate that the total grid dimensions do not exceed the physical label size.

        :raises ValueError: If grid dimensions exceed the physical label size.
        """
        total_width_mm = sum(self.column_widths.get(col, 0) for col in range(self.cols))
        total_height_mm = sum(self.row_heights.get(row, 0) for row in range(self.rows))
        if total_width_mm > self.real_width_mm or total_height_mm > self.real_height_mm:
            raise ValueError(f"Grid dimensions ({total_width_mm} mm x {total_height_mm} mm) exceed physical label size "
                             f"({self.real_width_mm} mm x {self.real_height_mm} mm)")

    def render_grid_lines(self) -> str:
        """
        Generate ZPL code to render grid lines.

        :return: ZPL code for grid lines.
        """
        zpl_lines = []
        cumulative_x_px = 0
        for col in range(1, self.cols):
            width_mm = self.column_widths.get(col - 1, 0)
            cumulative_x_px += mm_to_pixels(width_mm, DPI)
            zpl_lines.append(f"^FO{cumulative_x_px},0^GB2,{self.label_height_px},2^FS")
        cumulative_y_px = 0
        for row in range(1, self.rows):
            height_mm = self.row_heights.get(row - 1, 0)
            cumulative_y_px += mm_to_pixels(height_mm, DPI)
            zpl_lines.append(f"^FO0,{cumulative_y_px}^GB{self.label_width_px},2,2^FS")
        return "\n".join(zpl_lines)

    def create(self) -> str:
        """
        Create the complete ZPL code for the grid label.

        :return: Complete ZPL code as a string.
        """
        self.validate_grid()
        offsets = self._calculate_cell_offsets()
        zpl_parts = ["^XA"]
        for row in range(self.rows):
            for col in range(self.cols):
                cell = self.cells[(col, row)]
                offset_x, offset_y = offsets[(col, row)]
                cell_zpl = cell.render(offset_x, offset_y, self.dummy_label)
                if cell_zpl:
                    zpl_parts.append(cell_zpl)
        if self.draw_grid_lines:
            zpl_parts.append(self.render_grid_lines())
        zpl_parts.append("^XZ")
        return "\n".join(zpl_parts)
