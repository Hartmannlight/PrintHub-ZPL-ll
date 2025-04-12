import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

logger = logging.getLogger(__name__)

class MicroControllerLabel(BaseLabelPreset):
    """
    MicroControllerLabel preset.

    Creates a label with a specific grid layout:

      Outer Grid (3 columns):
        - Column A: 4 mm wide (empty)
        - Column B: 20 mm wide (contains a nested grid)
        - Column C: occupies the remaining width (empty)

      In Column B:
        - A grid with 1 column and 2 rows:
            - Row 0: Fixed 20 mm high; contains a nested grid (B.0)
            - Row 1: Occupies the remaining height (empty)

      In Grid B.0:
        - A grid with 1 column and 2 rows (cells B.0.0 and B.0.1 of equal height):
            - In cell B.0.0:
                - A nested grid with 2 columns and 1 row:
                    - Cell B.0.0.a (1/3 of the width) contains a DataMatrix element
                      with an ID generated from category 'BTL' and type 'MCU'
                    - Cell B.0.0.b (2/3 of the width) displays the last 5 digits
                      of the timestamp (from the generated ID) converted to hexadecimal.
            - In cell B.0.1:
                - A Text element displays the provided mcu_type.
    """

    def __init__(self, label_width_mm: float, label_height_mm: float, mcu_type: str) -> None:
        """
        Initialize the MicroControllerLabel preset.

        :param label_width_mm: Total label width in millimeters.
        :param label_height_mm: Total label height in millimeters.
        :param mcu_type: The type information to display in cell B.0.1.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.mcu_type = mcu_type

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the MicroController label.

        :return: ZPL code as a string.
        """
        logger.debug("Creating MicroControllerLabel with width=%s mm, height=%s mm",
                     self.label_width_mm, self.label_height_mm)

        # Outer grid: 3 columns (A, B, C)
        col_a_width = 4.0  # 4 mm for column A (empty)
        col_b_width = 20.0  # 20 mm for column B
        col_c_width = self.label_width_mm - col_a_width - col_b_width  # remaining width

        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=3,
            rows=1,
            draw_grid_lines=False
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(2, 0, width_mm=col_c_width, height_mm=self.label_height_mm)

        # Grid in Column B (cell (1,0)): 1 column x 2 rows.
        # Row 0: fixed 20 mm high, Row 1: remaining height.
        grid_b = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        grid_b.set_cell_size(0, 0, width_mm=col_b_width, height_mm=20.0)
        grid_b.set_cell_size(0, 1, width_mm=col_b_width, height_mm=self.label_height_mm - 20.0)

        # In grid B, cell (0,0): create a nested grid with 1 column and 2 rows (B.0)
        # Both rows are of equal height (10 mm each, since 20 mm / 2).
        grid_b0 = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=20.0,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        half_b0_height = 20.0 / 2.0
        grid_b0.set_cell_size(0, 0, width_mm=col_b_width, height_mm=half_b0_height)
        grid_b0.set_cell_size(0, 1, width_mm=col_b_width, height_mm=half_b0_height)

        # In grid B.0, cell (0,0) -> create grid B.0.0 with 2 columns and 1 row.
        grid_b00 = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=half_b0_height,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        # Cell B.0.0.a is 1/3 of the width, B.0.0.b takes the remaining 2/3.
        cell_b00_a_width = col_b_width / 2
        cell_b00_b_width = col_b_width - cell_b00_a_width
        grid_b00.set_cell_size(0, 0, width_mm=cell_b00_a_width, height_mm=half_b0_height)
        grid_b00.set_cell_size(1, 0, width_mm=cell_b00_b_width, height_mm=half_b0_height)

        # Generate a DataMatrix element in cell B.0.0.a with an ID from category 'BTL' and type 'MCU'
        id_factory = IdFactory()
        generated_id = id_factory.generate_code("BTL", "MCU")
        mcu_id_element = DataMatrixElement.from_id(generated_id, center_horizontal=True, center_vertical=True)
        logger.debug("Generated MCU ID: %s", generated_id)

        # Extract the timestamp part: take the last 5 digits and convert to hexadecimal.
        try:
            timestamp_part = generated_id.split("-")[2]
            last_five = timestamp_part[-5:]
            hex_value = format(int(last_five), 'X')
        except (IndexError, ValueError) as e:
            logger.error("Error extracting timestamp for hex conversion: %s", e)
            hex_value = ""

        # Add the DataMatrix element to cell B.0.0.a.
        grid_b00.cell(0, 0).add_element(mcu_id_element)

        # Add a Text element with the hexadecimal value to cell B.0.0.b.
        grid_b00.cell(1, 0).add_element(TextElement(
            text=hex_value,
            center_horizontal=True,
            center_vertical=True
        ))

        # Add grid B.0.0 to grid B.0 in cell (0,0).
        grid_b0.cell(0, 0).add_element(GridElement(grid_b00))

        # In grid B.0, cell (0,1): add a Text element with the provided mcu_type.
        grid_b0.cell(0, 1).add_element(TextElement(
            text=self.mcu_type,
            center_horizontal=True,
            center_vertical=True
        ))

        # Add grid B.0 to grid B, cell (0,0).
        grid_b.cell(0, 0).add_element(GridElement(grid_b0))

        # Add grid B to the main grid, cell (1,0).
        main_grid.cell(1, 0).add_element(GridElement(grid_b))

        return main_grid.create()
