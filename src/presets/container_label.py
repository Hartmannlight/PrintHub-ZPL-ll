# src/presets/container_label.py
import logging
from src.presets.base import BaseLabelPreset
from src.grids.grid_label import GridLabel
from src.grids.grid_element import GridElement
from src.elements.text_element import TextElement
from src.utils.label_helpers import make_datamatrix

logger = logging.getLogger(__name__)


class ContainerLabel(BaseLabelPreset):
    """
    Preset for container labels:
      - Top half: content text centered
      - Bottom half: DataMatrix + position text in two columns
    """

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        content: str,
        position: str,
        id_category: str = "LAG",
        id_type: str = "KIST",
        module_ratio: int = 3,
    ) -> None:
        """
        :param label_width_mm: Label width in mm (>0)
        :param label_height_mm: Label height in mm (>0)
        :param content: Top text
        :param position: Bottom position text
        :param id_category: Category for DataMatrix ID
        :param id_type: Type for DataMatrix ID
        :param module_ratio: Module ratio for DataMatrix
        :raises ValueError: If dimensions are not positive
        """
        logger.debug(
            "Initializing ContainerLabel(width=%.1f, height=%.1f, content=%r, position=%r)",
            label_width_mm, label_height_mm, content, position,
        )
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.content = content
        self.position = position
        self.id_category = id_category
        self.id_type = id_type
        self.module_ratio = module_ratio

    def create_zpl(self) -> str:
        """
        Build ZPL for the container label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for ContainerLabel")
        half_h = self.label_height_mm / 2

        main = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=self.label_height_mm, cols=1, rows=2, draw_grid_lines=True)
        main.set_cell_size(0, 0, width_mm=self.label_width_mm, height_mm=half_h)
        main.set_cell_size(0, 1, width_mm=self.label_width_mm, height_mm=half_h)

        # Top cell
        main.cell(0, 0).add_element(TextElement(text=self.content, center_horizontal=True, center_vertical=True))

        # Bottom nested
        nested = GridLabel(real_width_mm=self.label_width_mm, real_height_mm=half_h, cols=2, rows=1, draw_grid_lines=True)
        left_w = self.label_width_mm / 4
        right_w = self.label_width_mm - left_w
        nested.set_cell_size(0, 0, width_mm=left_w, height_mm=half_h)
        nested.set_cell_size(1, 0, width_mm=right_w, height_mm=half_h)
        nested.cell(0, 0).add_element(make_datamatrix(self.id_category, self.id_type, module_ratio=self.module_ratio))
        nested.cell(1, 0).add_element(TextElement(text=self.position, center_horizontal=True, center_vertical=True))

        main.cell(0, 1).add_element(GridElement(nested))
        return main.create()
