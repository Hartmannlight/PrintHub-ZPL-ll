import logging

from numpy.ma.core import left_shift
from numpy.polynomial.legendre import legtrim
from win32con import lDefaultTab

from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.elements.data_matrix_element import DataMatrixElement
from src.utils.id_factory import IdFactory

logger = logging.getLogger(__name__)


class ContainerLabel(BaseLabelPreset):
    """
    Label preset for containers (boxes, drawers, bags, shelves, rooms, etc).

    Row0: arbitrary content text.
    Row1: two‑column grid with
      - left: DataMatrix (auto ID in LAG/KIST)
      - right: position text.
    """

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        content: str,
        position: str,
        id_category: str = "LAG",
        id_type: str = "KIST",
        module_ratio: int = 3
    ) -> None:
        """
        :param label_width_mm: total label width in millimeters
        :param label_height_mm: total label height in millimeters
        :param content: text to display on the top line
        :param position: text to display next to the DataMatrix code on the bottom line
        :param id_category: category for code generation (default "LAG" for storage)
        :param id_type: type for code generation (default "KIST" for box)
        :param module_ratio: DataMatrix module ratio
        """
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.content = content
        self.position = position
        self.id_category = id_category
        self.id_type = id_type
        self.module_ratio = module_ratio

    def create_zpl(self) -> str:
        """
        Build the ZPL for the two‑line container label.
        """
        # split the height into two equal rows
        row_height_mm = self.label_height_mm / 2

        # top‑level grid: 1 col × 2 rows
        main_grid = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=self.label_height_mm,
            cols=1, rows=2, draw_grid_lines=True
        )
        main_grid.set_cell_size(0, 0, self.label_width_mm, row_height_mm)
        main_grid.set_cell_size(0, 1, self.label_width_mm, row_height_mm)

        # Row 0 → plain centered text
        main_grid.cell(0, 0).add_element(
            TextElement(
                text=self.content,
                center_horizontal=True,
                center_vertical=True
            )
        )

        # Row 1 → nested 2 col × 1 row grid
        nested = GridLabel(
            real_width_mm=self.label_width_mm,
            real_height_mm=row_height_mm,
            cols=2, rows=1, draw_grid_lines=True
        )
        left_width = self.label_width_mm / 4
        right_width = self.label_width_mm - left_width
        nested.set_cell_size(0, 0, left_width, row_height_mm)
        nested.set_cell_size(1, 0, right_width, row_height_mm)

        # generate an ID and put a DataMatrix on the left
        id_factory = IdFactory()
        generated_id = id_factory.generate_code(self.id_category, self.id_type)
        nested.cell(0, 0).add_element(
            DataMatrixElement.from_id(
                generated_id,
                module_ratio=self.module_ratio,
                center_horizontal=True,
                center_vertical=True
            )
        )

        # position string on the right
        nested.cell(1, 0).add_element(
            TextElement(
                text=self.position,
                center_horizontal=True,
                center_vertical=True
            )
        )

        main_grid.cell(0, 1).add_element(GridElement(nested))
        return main_grid.create()
