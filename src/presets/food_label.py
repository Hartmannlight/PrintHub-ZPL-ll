from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

class FoodLabel(BaseLabelPreset):
    """
    Food Label preset.
    Creates a label where Column A displays the BBF date and a DataMatrix element
    (with a generated ID from category 'VBM' and type 'ESS'), and Column B displays food information.
    """
    def __init__(self, label_width_mm: float, label_height_mm: float, bbf_date: str, food: str) -> None:
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.bbf_date = bbf_date
        self.food = food

    def create_zpl(self) -> str:
        # Calculate the widths for two columns.
        col_a_width = self.label_width_mm / 3
        col_b_width = self.label_width_mm - col_a_width

        # Create the main grid: 2 columns x 1 row.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width, height_mm=self.label_height_mm)

        # Column A: Create a nested grid with 2 rows.
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
        # Add the BBF date in the first row.
        grid_a.cell(0, 0).add_element(TextElement(text=self.bbf_date, center_horizontal=True, center_vertical=True))
        # Generate the ID for the DataMatrix element.
        id_factory = IdFactory()
        generated_id = id_factory.generate_code("VBM", "ESS")
        # Add the DataMatrix element in the second row.
        grid_a.cell(0, 1).add_element(DataMatrixElement.from_id(generated_id, module_ratio=3, center_horizontal=True, center_vertical=True))
        grid_a_element = GridElement(grid_a)

        # Column B: Add a simple text element for the food information.
        food_text = TextElement(text=self.food, center_horizontal=True, center_vertical=True)

        # Add the nested elements to the main grid.
        main_grid.cell(0, 0).add_element(grid_a_element)
        main_grid.cell(1, 0).add_element(food_text)

        return main_grid.create()
