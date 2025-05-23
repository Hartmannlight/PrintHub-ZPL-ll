import logging
import requests
from io import BytesIO
from typing import Optional
from PIL import Image
from src.config import DPI, LOGGING_LEVEL
from src.utils.conversion import mm_to_inches

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=getattr(logging, LOGGING_LEVEL),
    format='[%(levelname)s] %(asctime)s - %(message)s'
)


class LabelaryClient:
    """
    Client for interacting with the Labelary API.

    Provides methods to render ZPL code into image data.
    """

    def __init__(self, dpi: int = DPI) -> None:
        """
        Initialize the LabelaryClient.

        :param dpi: Dots per inch for the printer.
        """
        logger.debug("Initializing LabelaryClient with DPI=%d", dpi)
        self.dpi = dpi
        self.base_url = "https://api.labelary.com/v1/printers"

    def _mm_to_inches(self, mm: float) -> float:
        """
        Convert millimeters to inches.

        :param mm: Value in millimeters.
        :return: Value in inches.
        """
        inches = mm_to_inches(mm)
        logger.debug("Converted %f mm to %f inches", mm, inches)
        return inches

    def _construct_url(self, width_mm: float, height_mm: float, index: int = 0) -> str:
        """
        Construct the Labelary API URL based on label dimensions in inches.

        :param width_mm: Label width in mm.
        :param height_mm: Label height in mm.
        :param index: Label index.
        :return: Constructed URL.
        """
        width_in = self._mm_to_inches(width_mm)
        height_in = self._mm_to_inches(height_mm)
        url = f"{self.base_url}/8dpmm/labels/{width_in}x{height_in}/{index}/"
        logger.debug("Constructed Labelary URL: %s", url)
        return url

    def get_label_image(self, zpl_code: str, width_mm: float, height_mm: float, index: int = 0) -> bytes:
        """
        Send ZPL code to the Labelary API and return the rendered image data.

        :param zpl_code: ZPL code.
        :param width_mm: Label width in mm.
        :param height_mm: Label height in mm.
        :param index: Label index.
        :return: Image data as bytes.
        :raises: Exception if the API response indicates an error.
        """
        url = self._construct_url(width_mm, height_mm, index)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = requests.post(url, data=zpl_code, headers=headers)
        response.raise_for_status()
        logger.debug("Received image data from Labelary API")
        return response.content

    def preview_label(self, zpl_code: str, width_mm: float, height_mm: float) -> Optional[Image.Image]:
        """
        Render a preview of the label by returning a PNG image generated by the Labelary API.

        :param zpl_code: ZPL code.
        :param width_mm: Label width in mm.
        :param height_mm: Label height in mm.
        :return: Preview image or None if rendering fails.
        """
        width_in = self._mm_to_inches(width_mm)
        height_in = self._mm_to_inches(height_mm)
        url = f"{self.base_url}/8dpmm/labels/{width_in}x{height_in}/0/"
        headers = {'Accept': 'image/png'}
        files = {'file': zpl_code}

        response = requests.post(url, headers=headers, files=files, stream=True)
        if response.status_code == 200:
            logger.debug("Preview image successfully retrieved from Labelary API")
            return Image.open(BytesIO(response.content))
        else:
            logger.error("Error rendering preview: %s", response.text)
            return None
