import logging
from src.config import DEFAULT_BARCODE_QUALITY
from src.elements.elements import Element
from src.utils.id_factory import IdFactory

logger = logging.getLogger(__name__)

class DataMatrixElement(Element):
    """
    Represents a DataMatrix barcode element.

    The normal constructor accepts any arbitrary text without validation.
    The class method `from_id` validates that the provided ID is in the correct
    format ('CAT-TYP-TIMESTAMP') and raises a ValueError if not.
    """

    def __init__(self, data: str, x: int = 0, y: int = 0,
                 module_ratio: int = 2, quality: int = DEFAULT_BARCODE_QUALITY,
                 center_horizontal: bool = False, center_vertical: bool = False) -> None:
        """
        Initialize a DataMatrixElement with the provided data.

        :param data: The data for the barcode (arbitrary text is allowed).
        :param x: X-coordinate.
        :param y: Y-coordinate.
        :param module_ratio: Module ratio for the barcode.
        :param quality: Barcode quality (e.g. 200 for ECC 200).
        :param center_horizontal: If True, centers the element horizontally.
        :param center_vertical: If True, centers the element vertically.
        """
        logger.debug("Creating DataMatrixElement with data: %s", data)
        self.data = data
        self.x = x
        self.y = y
        self.module_ratio = module_ratio
        self.quality = quality
        self.center_horizontal = center_horizontal
        self.center_vertical = center_vertical
        self.size = self.module_ratio * 18

    @classmethod
    def from_id(cls, id: str, x: int = 0, y: int = 0,
                module_ratio: int = 2, quality: int = DEFAULT_BARCODE_QUALITY,
                center_horizontal: bool = False, center_vertical: bool = False) -> "DataMatrixElement":
        """
        Alternative constructor that validates the provided ID.

        The ID must follow the format 'CAT-TYP-TIMESTAMP'. If the validation fails,
        a ValueError is raised.

        :param id: The ID string to use.
        :param x: X-coordinate.
        :param y: Y-coordinate.
        :param module_ratio: Module ratio.
        :param quality: Barcode quality.
        :param center_horizontal: If True, centers the element horizontally.
        :param center_vertical: If True, centers the element vertically.
        :return: A DataMatrixElement instance with the validated ID.
        :raises ValueError: If the provided ID is invalid.
        """
        id_factory = IdFactory()
        if not id_factory.validate_code(id):
            logger.error("Invalid ID provided to DataMatrixElement.from_id: %s", id)
            raise ValueError("Invalid ID. The ID must follow the format 'CAT-TYP-TIMESTAMP'.")
        return cls(id, x=x, y=y, module_ratio=module_ratio,
                   quality=quality, center_horizontal=center_horizontal,
                   center_vertical=center_vertical)

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the DataMatrix element to its corresponding ZPL code.

        :param label: The parent label.
        :param offset_x: Horizontal offset for the element.
        :param offset_y: Vertical offset for the element.
        :return: A string containing the ZPL code for the element.
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
