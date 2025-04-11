import math
import logging
from typing import Optional, Tuple
from PIL import Image
from src.elements.elements import Element

logger = logging.getLogger(__name__)


class ImageElement(Element):
    """
    Represents an image element in a label.

    Converts the image file to a hexadecimal data string for ZPL rendering.
    """

    def __init__(self, file_path: str, x: int = 0, y: int = 0,
                 width_mm: Optional[float] = None, height_mm: Optional[float] = None,
                 center_horizontal: bool = False, center_vertical: bool = False) -> None:
        """
        Initialize an ImageElement.

        :param file_path: Path to the image file.
        :param x: X-coordinate.
        :param y: Y-coordinate.
        :param width_mm: Desired image width in millimeters.
        :param height_mm: Desired image height in millimeters.
        :param center_horizontal: Flag to center horizontally.
        :param center_vertical: Flag to center vertically.
        """
        logger.debug("Creating ImageElement from file: %s", file_path)
        self.file_path = file_path
        self.x = x
        self.y = y
        self.width_mm = width_mm
        self.height_mm = height_mm
        self.center_horizontal = center_horizontal
        self.center_vertical = center_vertical

        self.image = Image.open(file_path).convert("1")
        if self.width_mm is not None and self.height_mm is not None:
            target_width = int(self.width_mm / 25.4 * 203)
            target_height = int(self.height_mm / 25.4 * 203)
            logger.debug("Resizing image to: %d x %d", target_width, target_height)
            self.image = self.image.resize((target_width, target_height), resample=Image.Resampling.LANCZOS)
        self.width_px, self.height_px = self.image.size
        logger.debug("Image size (px): %d x %d", self.width_px, self.height_px)

    def _convert_image_to_zpl_data(self) -> Tuple[int, int, str]:
        """
        Convert the image to ZPL hexadecimal data.

        :return: A tuple of (total_bytes, bytes_per_row, hex_data).
        """
        bytes_per_row = math.ceil(self.width_px / 8)
        total_bytes = bytes_per_row * self.height_px
        hex_data = ""
        for y in range(self.height_px):
            byte = 0
            bit_count = 0
            for x in range(self.width_px):
                pixel = self.image.getpixel((x, y))
                bit = 1 if pixel == 0 else 0
                byte = (byte << 1) | bit
                bit_count += 1
                if bit_count == 8:
                    hex_data += f"{byte:02X}"
                    byte = 0
                    bit_count = 0
            if bit_count > 0:
                byte = byte << (8 - bit_count)
                hex_data += f"{byte:02X}"
        logger.debug("Converted image to ZPL data: total_bytes=%d, bytes_per_row=%d", total_bytes, bytes_per_row)
        return total_bytes, bytes_per_row, hex_data

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        """
        Convert the image element to its corresponding ZPL code.

        :param label: The parent label.
        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :return: ZPL code as a string.
        """
        final_x = self.x
        final_y = self.y
        if self.center_horizontal:
            final_x = int((label.width_px - self.width_px) / 2 + self.x)
        if self.center_vertical:
            final_y = int((label.height_px - self.height_px) / 2 + self.y)
        final_x = max(final_x + offset_x, 0)
        final_y = max(final_y + offset_y, 0)
        total_bytes, bytes_per_row, hex_data = self._convert_image_to_zpl_data()
        zpl_code = f"^FO{final_x},{final_y}^GFA,{total_bytes},{total_bytes},{bytes_per_row},{hex_data}^FS"
        logger.debug("ImageElement ZPL: %s", zpl_code)
        return zpl_code
