import datetime
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.elements.line_element import LineElement
from src.config import DPI
from src.utils.conversion import mm_to_pixels
from src.presets.base import BaseLabelPreset


class CableTypeLabel(BaseLabelPreset):
    """
    Cable Type Label preset.

    This preset creates a label using a nested grid layout with sections for the "from" text,
    "to" text, cable length, specification, and a generated ID.
    """
    COL_B_WIDTH_MM = 20
    NUM_COLS_MAIN = 3
    NUM_ROWS_GRID_A = 3
    NUM_ROWS_GRID_C = 2
    LINE_THICKNESS = 2
    C_TOP_RATIO = 2 / 3
    DEFAULT_DRAW_GRID_LINES = True

    def __init__(self, label_width_mm: float, label_height_mm: float, from_text: str, to_text: str,
                 length: float, spec_text: str, type_abbr: str):
        """
        Initialize a CableTypeLabel.

        :param label_width_mm: Label width in mm.
        :param label_height_mm: Label height in mm.
        :param from_text: Text for the "from" section.
        :param to_text: Text for the "to" section.
        :param length: Cable length.
        :param spec_text: Specification text.
        :param type_abbr: Type abbreviation for the code (the category is fixed as "KAT").
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_text = from_text
        self.to_text = to_text
        self.length = length
        self.spec_text = spec_text
        self.type_abbr = type_abbr

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the cable type label.

        :return: ZPL code as a string.
        """
        col_a_width_mm = (self.label_width_mm - self.__class__.COL_B_WIDTH_MM) / 2
        col_b_width_mm = self.__class__.COL_B_WIDTH_MM

        # Main grid: 3 columns x 1 row.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=self.__class__.NUM_COLS_MAIN,
            rows=1,
            draw_grid_lines=self.__class__.DEFAULT_DRAW_GRID_LINES
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a_width_mm, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width_mm, height_mm=self.label_height_mm)
        main_grid.set_cell_size(2, 0, width_mm=col_a_width_mm, height_mm=self.label_height_mm)

        # Nested grid for column A ("from", "to", length).
        grid_a = GridLabel(
            real_width_mm=col_a_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=self.__class__.NUM_ROWS_GRID_A,
            draw_grid_lines=self.__class__.DEFAULT_DRAW_GRID_LINES
        )
        cell_height_a_mm = self.label_height_mm / self.__class__.NUM_ROWS_GRID_A
        for row in range(self.__class__.NUM_ROWS_GRID_A):
            grid_a.set_cell_size(0, row, width_mm=col_a_width_mm, height_mm=cell_height_a_mm)
        grid_a.cell(0, 0).add_element(TextElement(text=self.from_text, center_horizontal=True, center_vertical=True))
        grid_a.cell(0, 1).add_element(TextElement(text=self.to_text, center_horizontal=True, center_vertical=True))
        grid_a.cell(0, 2).add_element(TextElement(text=f"{self.length} cm", center_horizontal=True, center_vertical=True))
        grid_a_element = GridElement(grid_a)

        # Vertical line for column B.
        cell_width_b_px = mm_to_pixels(self.__class__.COL_B_WIDTH_MM, DPI)
        cell_height_b_px = mm_to_pixels(self.label_height_mm, DPI)
        center_x = cell_width_b_px // 2
        line_element = LineElement(x1=center_x, y1=0, x2=center_x, y2=cell_height_b_px, thickness=self.__class__.LINE_THICKNESS)

        # Nested grid for column C ("spec", generated ID).
        grid_c = GridLabel(
            real_width_mm=col_a_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=self.__class__.NUM_ROWS_GRID_C,
            draw_grid_lines=self.__class__.DEFAULT_DRAW_GRID_LINES
        )
        top_height_c_mm = self.label_height_mm * self.__class__.C_TOP_RATIO
        bottom_height_c_mm = self.label_height_mm * (1 - self.__class__.C_TOP_RATIO)
        grid_c.set_cell_size(0, 0, width_mm=col_a_width_mm, height_mm=top_height_c_mm)
        grid_c.set_cell_size(0, 1, width_mm=col_a_width_mm, height_mm=bottom_height_c_mm)
        grid_c.cell(0, 0).add_element(TextElement(text=self.spec_text, center_horizontal=True, center_vertical=True))
        grid_c.cell(0, 1).add_element(DataMatrixElement.from_text("", category="KAT", type_abbr=self.type_abbr))
        grid_c_element = GridElement(grid_c)

        main_grid.cell(0, 0).add_element(grid_a_element)
        main_grid.cell(1, 0).add_element(line_element)
        main_grid.cell(2, 0).add_element(grid_c_element)

        return main_grid.create()
