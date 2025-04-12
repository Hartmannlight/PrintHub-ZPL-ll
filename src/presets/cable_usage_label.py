import logging
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.presets.base import BaseLabelPreset


class CableUsageLabel(BaseLabelPreset):
    """
    Cable Usage Label preset.

    Creates a label with two columns (A and B), each composed of a nested grid with 2 rows.
    Column A displays the content of 'from_text' in both cells.
    Column B displays the content of 'to_text' in both cells.
    IDs and DataMatrix elements are not used in this layout.
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, from_text: str, to_text: str):
        """
        Initialize a CableUsageLabel.

        :param label_width_mm: Label width in mm.
        :param label_height_mm: Label height in mm.
        :param from_text: Text for the left column (Column A).
        :param to_text: Text for the right column (Column B).
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.from_text = from_text
        self.to_text = to_text

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the cable usage label with the updated layout.

        The label contains two columns, each with a nested grid of 2 rows:
        - Column A: Both cells display the content of 'from_text'.
        - Column B: Both cells display the content of 'to_text'.

        :return: ZPL code as a string.
        """
        column_width_mm = self.label_width_mm / 2

        # Create the grid for the left column (Column A)
        grid_from = GridLabel(
            real_width_mm=column_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        row_height_from = self.label_height_mm / 2
        for row in range(2):
            grid_from.set_cell_size(0, row, width_mm=column_width_mm, height_mm=row_height_from)
            grid_from.cell(0, row).add_element(
                TextElement(text=self.from_text, center_horizontal=True, center_vertical=True)
            )

        # Create the grid for the right column (Column B)
        grid_to = GridLabel(
            real_width_mm=column_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        row_height_to = self.label_height_mm / 2
        for row in range(2):
            grid_to.set_cell_size(0, row, width_mm=column_width_mm, height_mm=row_height_to)
            grid_to.cell(0, row).add_element(
                TextElement(text=self.to_text, center_horizontal=True, center_vertical=True)
            )

        # Create the main grid with two columns.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=column_width_mm, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=column_width_mm, height_mm=self.label_height_mm)
        main_grid.cell(0, 0).add_element(GridElement(grid_from))
        main_grid.cell(1, 0).add_element(GridElement(grid_to))

        return main_grid.create()
