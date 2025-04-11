import numpy as np
import logging
from io import BytesIO
from typing import Optional, Tuple
from PIL import Image, ImageDraw
from src.utils.labelary_client import LabelaryClient
from src.config import DPI
from src.utils.conversion import pixels_to_mm

logger = logging.getLogger(__name__)


class ZPLElementMeasurer:
    """
    Utility class to measure rendered ZPL-II code.

    Retrieves image data via the LabelaryClient.
    """

    def __init__(self, width_px: int = 3045, height_px: int = 3045, dpi: int = DPI,
                 labelary_client: Optional[LabelaryClient] = None) -> None:
        """
        Initialize the ZPLElementMeasurer.

        :param width_px: Pixel width of the measurement area.
        :param height_px: Pixel height of the measurement area.
        :param dpi: Dots per inch.
        :param labelary_client: Optional LabelaryClient instance.
        """
        logger.debug("Initializing ZPLElementMeasurer with width_px=%d, height_px=%d, dpi=%d", width_px, height_px, dpi)
        self.width_px = width_px
        self.height_px = height_px
        self.dpi = dpi
        self.labelary_client = labelary_client or LabelaryClient(dpi=dpi)

    @classmethod
    def default(cls) -> "ZPLElementMeasurer":
        """
        Return a default instance of ZPLElementMeasurer.

        :return: A ZPLElementMeasurer instance.
        """
        return cls()

    def _calculate_dimensions_mm(self) -> Tuple[float, float]:
        """
        Calculate the measurement area dimensions in millimeters.

        :return: Tuple of (width_mm, height_mm).
        """
        width_mm = pixels_to_mm(self.width_px, self.dpi)
        height_mm = pixels_to_mm(self.height_px, self.dpi)
        logger.debug("Calculated dimensions: %f mm x %f mm", width_mm, height_mm)
        return width_mm, height_mm

    def get_label_image(self, zpl_code: str, index: int = 0) -> bytes:
        """
        Retrieve image data for the rendered ZPL code.

        :param zpl_code: ZPL code.
        :param index: Label index.
        :return: Image data as bytes.
        """
        width_mm, height_mm = self._calculate_dimensions_mm()
        img_data = self.labelary_client.get_label_image(zpl_code, width_mm, height_mm, index=index)
        logger.debug("Retrieved label image data of length %d", len(img_data))
        return img_data

    def find_text_bbox(self, image: Image.Image) -> Optional[Tuple[int, int, int, int]]:
        """
        Find the bounding box of non-white pixels in the image.

        :param image: PIL Image.
        :return: Bounding box (x0, y0, x1, y1) or None if not found.
        """
        gray_image = image.convert("L")
        arr = np.array(gray_image)
        mask = arr < 250
        coords = np.argwhere(mask)
        if coords.size == 0:
            logger.debug("No non-white pixels found in the image.")
            return None
        y0, x0 = coords.min(axis=0)
        y1, x1 = coords.max(axis=0)
        logger.debug("Found bounding box: (%d, %d, %d, %d)", x0, y0, x1, y1)
        return x0, y0, x1, y1

    def measure_zpl(self, zpl_code: str) -> Tuple[int, int, int]:
        """
        Render the ZPL code, measure the content's bounding box and return its width, height,
        and top padding in pixels.

        :param zpl_code: ZPL code.
        :return: Tuple of (width, height, top_padding).
        """
        img_data = self.get_label_image(zpl_code)
        image = Image.open(BytesIO(img_data))
        bbox = self.find_text_bbox(image)
        if bbox:
            x0, y0, x1, y1 = bbox
            width = x1 - x0
            height = y1 - y0
            logger.debug("Measured ZPL: width=%d, height=%d, top_padding=%d", width, height, y0)
            return (width, height, y0)
        logger.debug("No bounding box found, returning zeros.")
        return (0, 0, 0)

    def preview(self, zpl_code: str) -> Image.Image:
        """
        Generate a preview image with a red bounding box around the rendered content.

        :param zpl_code: ZPL code.
        :return: PIL Image with preview.
        """
        img_data = self.get_label_image(zpl_code)
        image = Image.open(BytesIO(img_data))
        bbox = self.find_text_bbox(image)
        if bbox:
            draw = ImageDraw.Draw(image)
            draw.rectangle(bbox, outline="red", width=2)
            logger.debug("Generated preview image with bounding box.")
        return image
