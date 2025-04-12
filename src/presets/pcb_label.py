import datetime
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

class PcbLabel(BaseLabelPreset):
    """
    PCB Label preset.

    Creates a label with two columns:
      - Column A (5/16 of the label width) contains a DataMatrix element with an ID
        generated from category 'BTL' and type 'PCB'.
      - Column B (the remaining width) contains a nested grid with two rows:
          * Row 0 contains a nested grid with 2 columns:
              - Cell A: displays the provided project text.
              - Cell B: displays the current date and time.
          * Row 1 displays the provided info text.
    """
    def __init__(self, label_width_mm: float, label_height_mm: float, project: str, info: str) -> None:
        """
        Initialize the PCB Label preset.

        :param label_width_mm: Label width in millimeters.
        :param label_height_mm: Label height in millimeters.
        :param project: Project description text.
        :param info: Additional information text.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.project = project
        self.info = info

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the PCB label.

        :return: ZPL code as a string.
        """
        # Calculate column widths.
        col_a_width = self.label_width_mm * 5 / 16
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

        # Column A: DataMatrix element with an ID from category 'BTL' and type 'PCB'.
        id_factory = IdFactory()
        generated_id = id_factory.generate_code("BTL", "PCB")
        data_matrix = DataMatrixElement.from_id(
            generated_id,
            module_ratio=4,
            center_horizontal=True,
            center_vertical=True
        )
        main_grid.cell(0, 0).add_element(data_matrix)

        # Column B: A nested grid with 2 rows and 1 column.
        grid_b = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        row_height = self.label_height_mm / 2
        grid_b.set_cell_size(0, 0, width_mm=col_b_width, height_mm=row_height)
        grid_b.set_cell_size(0, 1, width_mm=col_b_width, height_mm=row_height)

        # In row 0, a nested grid with 2 columns (for project text and date/time).
        grid_b0 = GridLabel(
            real_width_mm=col_b_width,
            real_height_mm=row_height,
            cols=2,
            rows=1,
            draw_grid_lines=True
        )
        col_width_b0 = col_b_width / 2
        grid_b0.set_cell_size(0, 0, width_mm=col_width_b0, height_mm=row_height)
        grid_b0.set_cell_size(1, 0, width_mm=col_width_b0, height_mm=row_height)
        grid_b0.cell(0, 0).add_element(TextElement(text=self.project, center_horizontal=True, center_vertical=True))
        current_datetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        grid_b0.cell(1, 0).add_element(TextElement(text=current_datetime, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 0).add_element(GridElement(grid_b0))

        # Row 1: display the provided info.
        grid_b.cell(0, 1).add_element(TextElement(text=self.info, center_horizontal=True, center_vertical=True))

        main_grid.cell(1, 0).add_element(GridElement(grid_b))
        return main_grid.create()
