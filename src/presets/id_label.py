# src/presets/id_label.py
import logging
from typing import Optional
from src.presets.base_label import BaseLabelPreset
from src.label import Label
from src.elements.text_element import TextElement
from src.utils.label_helpers import make_datamatrix

logger = logging.getLogger(__name__)


class IdLabel(BaseLabelPreset):
    """
    Preset for generic ID labels:
      - DataMatrix + optional date text.
    """

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        id_category: str = "ELE",
        id_type: str = "STGS",
        module_ratio: int = 3,
        padding_x: int = 5,
        padding_y: int = 5,
        print_date: bool = True,
        date_override: Optional[str] = None,
        date_font_size: int = 10,
    ) -> None:
        """
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :param id_category: Category for ID
        :param id_type: Type for ID
        :param module_ratio: DataMatrix module ratio
        :param padding_x: Horizontal padding in px
        :param padding_y: Vertical padding in px
        :param print_date: Whether to print date
        :param date_override: Optional date override (YYYY-MM-DD)
        :param date_font_size: Font size for date text
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing IdLabel(width=%.1f, height=%.1f, cat=%s, type=%s)",
                     label_width_mm, label_height_mm, id_category, id_type)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.id_category = id_category
        self.id_type = id_type
        self.module_ratio = module_ratio
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.print_date = print_date
        self.date_override = date_override
        self.date_font_size = date_font_size

    def create_zpl(self) -> str:
        """
        Build ZPL: DataMatrix plus optional date.

        :return: ZPL code as string.
        """
        logger.debug("Starting create_zpl for IdLabel")
        matrix = make_datamatrix(
            self.id_category,
            self.id_type,
            module_ratio=self.module_ratio,
            center_horizontal=False,
            center_vertical=False,
        )
        matrix.x = self.padding_x
        matrix.y = self.padding_y

        elements = [matrix]
        if self.print_date:
            date_str = self.date_override or self._extract_date_from_id(matrix.data)
            if date_str:
                text_x = self.padding_x * 2 + matrix.size
                text_y = self.padding_y
                elements.append(TextElement(text=date_str, x=text_x, y=text_y, font_size=self.date_font_size))

        return Label(*elements, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl

    def _extract_date_from_id(self, code: str) -> str:
        """
        Extract date (YYYY-MM-DD) from 'CAT-TYP-TIMESTAMP'.

        :param code: The generated ID string.
        :return: Date string or empty on failure.
        """
        try:
            ts = int(code.split("-")[2]) / 1000.0
            return __import__("datetime").datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            logger.warning("Failed to parse date from ID: %s", code)
            return ""
