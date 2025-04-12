from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

class PowerSupplyLabel(BaseLabelPreset):
    """
    Power Supply Label preset.

    Creates a label with three columns:
      - Column A (3/16 of the label width) contains a DataMatrix element with an ID from category 'ELE' and type 'NETZ'.
      - Columns B and C are equally sized and occupy the remaining width; each column contains a nested grid
        with 2 rows (1 column each).
          * Column B:
              - Row 0 displays the provided voltage ($volt).
              - Row 1 displays the provided AC/DC information ($acdc).
          * Column C:
              - Row 0 displays the provided current ($amps).
              - Row 1 displays the provided plug type ($plug).
    """
    def __init__(self, label_width_mm: float, label_height_mm: float, volt: str, acdc: str, amps: str, plug: str) -> None:
        """
        Initialize the Power Supply Label preset.

        :param label_width_mm: Label width in millimeters.
        :param label_height_mm: Label height in millimeters.
        :param volt: Voltage information.
        :param acdc: AC/DC information.
        :param amps: Current (amperage) information.
        :param plug: Plug type information.
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.volt = volt
        self.acdc = acdc
        self.amps = amps
        self.plug = plug

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the Power Supply label.

        :return: ZPL code as a string.
        """
        col_a_width = self.label_width_mm * 3 / 16
        remaining_width = self.label_width_mm - col_a_width
        col_b_width = remaining_width / 2
        col_c_width = remaining_width / 2

        # Create the main grid: 3 columns x 1 row.
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=3,
            rows=1,
            draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, width_mm=col_a_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(1, 0, width_mm=col_b_width, height_mm=self.label_height_mm)
        main_grid.set_cell_size(2, 0, width_mm=col_c_width, height_mm=self.label_height_mm)

        # Column A: DataMatrix element with an ID from category 'ELE' and type 'NETZ'.
        id_factory = IdFactory()
        generated_id = id_factory.generate_code("ELE", "NETZ")
        data_matrix = DataMatrixElement.from_id(
            generated_id,
            module_ratio=3,
            center_horizontal=True,
            center_vertical=True
        )
        main_grid.cell(0, 0).add_element(data_matrix)

        # Column B: Nested grid with 2 rows.
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
        grid_b.cell(0, 0).add_element(TextElement(text=self.volt, center_horizontal=True, center_vertical=True))
        grid_b.cell(0, 1).add_element(TextElement(text=self.acdc, center_horizontal=True, center_vertical=True))
        main_grid.cell(1, 0).add_element(GridElement(grid_b))

        # Column C: Nested grid with 2 rows.
        grid_c = GridLabel(
            real_width_mm=col_c_width,
            real_height_mm=self.label_height_mm,
            cols=1,
            rows=2,
            draw_grid_lines=True
        )
        grid_c.set_cell_size(0, 0, width_mm=col_c_width, height_mm=row_height)
        grid_c.set_cell_size(0, 1, width_mm=col_c_width, height_mm=row_height)
        grid_c.cell(0, 0).add_element(TextElement(text=self.amps, center_horizontal=True, center_vertical=True))
        grid_c.cell(0, 1).add_element(TextElement(text=self.plug, center_horizontal=True, center_vertical=True))
        main_grid.cell(2, 0).add_element(GridElement(grid_c))

        return main_grid.create()
