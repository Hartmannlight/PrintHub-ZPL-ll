import logging
from src.config import DEFAULT_BARCODE_QUALITY
from src.elements.elements import Element
from src.utils.id_factory import IdFactory

logger = logging.getLogger(__name__)


class DataMatrixElement(Element):
    """
    Represents a DataMatrix barcode element.

    If validation is enabled (validate_existing=True), the provided ID string is validated using IdFactory.
    If the ID is invalid, an error is logged and an exception is raised.
    Supports centered rendering via the center_horizontal and center_vertical parameters.
    """

    def __init__(self, data: str, x: int = 0, y: int = 0,
                 module_ratio: int = 2, quality: int = DEFAULT_BARCODE_QUALITY,
                 center_horizontal: bool = False, center_vertical: bool = False,
                 validate_existing: bool = False) -> None:
        """
        Initialize a DataMatrixElement.

        :param data: The data for the barcode.
        :param x: X-coordinate.
        :param y: Y-coordinate.
        :param module_ratio: Module ratio.
        :param quality: Barcode quality.
        :param center_horizontal: Flag to center horizontally.
        :param center_vertical: Flag to center vertically.
        :param validate_existing: If True, validates the provided data using IdFactory.
        """
        logger.debug("Creating DataMatrixElement with data: %s", data)
        self.id_factory = IdFactory()
        if validate_existing and not self.id_factory.validate_code(data):
            logger.error("Invalid ID in DataMatrixElement: %s", data)
            raise ValueError("Invalid ID. The ID must follow the format 'CAT-TYP-TIMESTAMP'.")
        self.data = data
        self.x = x
        self.y = y
        self.module_ratio = module_ratio
        self.quality = quality
        self.center_horizontal = center_horizontal
        self.center_vertical = center_vertical
        self.size = self.module_ratio * 18

    @classmethod
    def from_text(cls, text: str, category: str = None, type_abbr: str = None,
                  x: int = 0, y: int = 0, module_ratio: int = 2,
                  quality: int = DEFAULT_BARCODE_QUALITY,
                  center_horizontal: bool = False, center_vertical: bool = False) -> "DataMatrixElement":
        """
        Alternative constructor.

        If free text is provided that is not a valid ID, and if category and type are provided,
        a valid ID is generated using IdFactory.

        :param text: The input text.
        :param category: Category abbreviation.
        :param type_abbr: Type abbreviation.
        :return: A DataMatrixElement instance.
        """
        id_factory = IdFactory()
        if not id_factory.validate_code(text):
            if category is None or type_abbr is None:
                logger.error("Category and type must be provided to generate a valid ID from free text. Provided text: %s", text)
                raise ValueError("Category and type must be provided to generate a valid ID.")
            generated = id_factory.generate_code(category, type_abbr)
            return cls(generated, x=x, y=y, module_ratio=module_ratio, quality=quality,
                       center_horizontal=center_horizontal, center_vertical=center_vertical,
                       validate_existing=True)
        else:
            return cls(text, x=x, y=y, module_ratio=module_ratio, quality=quality,
                       center_horizontal=center_horizontal, center_vertical=center_vertical,
                       validate_existing=True)

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the DataMatrix element to its corresponding ZPL code.

        :param label: The parent label.
        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :return: ZPL code as a string.
        """
        final_x = self.x
        final_y = self.y
        if self.center_horizontal:
            final_x = int((label.width_px - self.size) / 2 + self.x)
        if self.center_vertical:
            final_y = int((label.height_px - self.size) / 2 + self.y)
        final_x = max(final_x + offset_x, 0)
        final_y = max(final_y + offset_y, 0)
        zpl_code = f"^FO{final_x},{final_y}^BXN,{self.module_ratio},{self.quality}^FD{self.data}^FS"
        logger.debug("DataMatrixElement ZPL: %s", zpl_code)
        return zpl_code

    def __repr__(self):
        return f"<DataMatrixElement data={self.data}>"
