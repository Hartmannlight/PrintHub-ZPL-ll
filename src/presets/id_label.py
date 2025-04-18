import logging
import datetime
from typing import Optional
from src.presets.base import BaseLabelPreset
from src.label import Label
from src.elements.data_matrix_element import DataMatrixElement
from src.elements.text_element import TextElement
from src.utils.id_factory import IdFactory
from src.config import DPI, DEFAULT_FONT

logger = logging.getLogger(__name__)


class IdLabel(BaseLabelPreset):
    """
    Generic preset that prints a DataMatrix code and an optional date string.

    The DataMatrix ID is generated at runtime (CATEGORY‑TYPE‑TIMESTAMP).
    You can control:
      - module_ratio (symbol size)
      - x/y padding from origin
      - whether to print a date to the right
      - supply your own date or auto‑extract from the ID
      - date font size (always small)
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
        date: Optional[str] = None,
        date_font_size: int = 10
    ) -> None:
        """
        :param label_width_mm: total label width in millimeters
        :param label_height_mm: total label height in millimeters
        :param id_category: category for ID generation (default "ELE")
        :param id_type: type for ID generation (default "STGS")
        :param module_ratio: DataMatrix module size factor
        :param padding_x: horizontal padding in pixels
        :param padding_y: vertical padding in pixels
        :param print_date: whether to print a date string
        :param date: explicit date string to print (if None, extract from generated ID)
        :param date_font_size: font size for the date text
        """
        logger.debug(
            "Initializing DataMatrixLabel(cat=%s, type=%s, ratio=%d, pad=(%d,%d), print_date=%s)",
            id_category, id_type, module_ratio, padding_x, padding_y, print_date
        )
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.id_category = id_category
        self.id_type = id_type
        self.module_ratio = module_ratio
        self.padding_x = padding_x
        self.padding_y = padding_y
        self.print_date = print_date
        self.date_override = date
        self.date_font_size = date_font_size

    def _extract_date_from_id(self, code: str) -> str:
        """
        Given an ID of form CAT-TYP-TIMESTAMP, return a YYYY‑MM‑DD string.
        """
        try:
            ts = int(code.split("-")[2]) / 1000.0
            return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except Exception:
            logger.warning("Failed to extract date from ID '%s'", code)
            return ""

    def create_zpl(self) -> str:
        """
        Build and return the ZPL code for this DataMatrix + optional date.
        """
        id_factory = IdFactory()
        generated_id = id_factory.generate_code(self.id_category, self.id_type)
        logger.debug("Generated ID for DataMatrix: %s", generated_id)

        matrix = DataMatrixElement.from_id(
            generated_id,
            x=self.padding_x,
            y=self.padding_y,
            module_ratio=self.module_ratio,
            center_horizontal=False,
            center_vertical=False
        )

        elements = [matrix]

        if self.print_date:
            date_str = (
                self.date_override
                if self.date_override is not None
                else self._extract_date_from_id(generated_id)
            )
            if date_str:
                text_x = self.padding_x + matrix.size + self.padding_x
                text_y = self.padding_y
                elements.append(
                    TextElement(
                        text=date_str,
                        x=text_x,
                        y=text_y,
                        font=DEFAULT_FONT,
                        font_size=self.date_font_size,
                        center_horizontal=False,
                        center_vertical=False
                    )
                )

        return Label(*elements, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl
