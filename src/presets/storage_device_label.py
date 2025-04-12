from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

class StorageDeviceLabel(BaseLabelPreset):
    """
    Storage Device Label preset.

    Creates a label with two columns:
      - Column A (one third of the label width) contains a nested grid with two rows:
          * Row 0 displays the provided size.
          * Row 1 contains a DataMatrix element with an ID from category 'MED' and type 'STGS'.
      - Column B (remaining width) displays the provided information.
    """
    def __init__(self, label_width_mm: float, label_height_mm: float, size: str, info: str) -> None:
        """
        Initialize the Storage Device Label preset.

        :param label_width_mm: Label width in millimeters.
        :param label_height_mm: Label height in millimeters.
        :param size: Size information.
        :param info: Additional information.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.size = size
        self.info = info

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the Storage Device label.

        :return: ZPL code as a string.
        """
        col_a_width = self.label_width_mm / 3
        col_b_width = self.label_width_mm - col_a_width

        # Create main grid: 2 columns x 1 row.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width, height_mm=self.label_height_mm)

        # Column A: Nested grid with 2 rows.
        grid_a = GridLabel(
            real_width_mm=col_a_width,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        row_height = self.label_height_mm / 2
        grid_a.set_cell_size(0, 0, width_mm=col_a_width, height_mm=row_height)
        grid_a.set_cell_size(0, 1, width_mm=col_a_width, height_mm=row_height)
        grid_a.cell(0, 0).add_element(TextElement(text=self.size, center_horizontal=True, center_vertical=True))
        id_factory = IdFactory()
        generated_id = id_factory.generate_code("MED", "STGS")
        data_matrix = DataMatrixElement.from_id(
            generated_id,
            module_ratio=3,
            center_horizontal=True,
            center_vertical=True
        )
        grid_a.cell(0, 1).add_element(data_matrix)
        main_grid.cell(0, 0).add_element(GridElement(grid_a))

        # Column B: Display the provided info.
        main_grid.cell(1, 0).add_element(TextElement(text=self.info, center_horizontal=True, center_vertical=True))
        return main_grid.create()
