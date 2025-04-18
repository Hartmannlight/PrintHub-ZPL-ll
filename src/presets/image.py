# src/presets/image.py
import logging
from PIL import Image
from src.label import Label
from src.elements.image_element import ImageElement
from src.config import DPI

logger = logging.getLogger(__name__)


def create(
    file_path: str,
    label_width_mm: float,
    label_height_mm: float,
    image_width_mm: float = None,
    image_height_mm: float = None,
) -> Label:
    """
    Create a Label with a centered image.

    :param file_path: Path to the image file.
    :param label_width_mm: Label width in mm (>0)
    :param label_height_mm: Label height in mm (>0)
    :param image_width_mm: Desired image width in mm
    :param image_height_mm: Desired image height in mm
    :raises FileNotFoundError: If file not found
    :raises ValueError: If dimensions are not positive
    :return: A Label containing the ImageElement
    """
    logger.debug("Starting image.create for %s", file_path)
    if label_width_mm <= 0 or label_height_mm <= 0:
        raise ValueError("Label dimensions must be positive")

    with Image.open(file_path) as img:
        orig_w_mm = img.width / DPI * 25.4
        orig_h_mm = img.height / DPI * 25.4

    image_width_mm = image_width_mm or orig_w_mm
    image_height_mm = image_height_mm or orig_h_mm

    elem = ImageElement(
        file_path,
        width_mm=image_width_mm,
        height_mm=image_height_mm,
        center_horizontal=True,
        center_vertical=True,
    )
    return Label(elem, width_mm=label_width_mm, height_mm=label_height_mm)
