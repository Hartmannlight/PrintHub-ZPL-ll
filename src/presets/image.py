from PIL import Image
from src.label import Label
from src.elements.image_element import ImageElement
from src.config import DPI


def create(file_path: str, label_width_mm: float, label_height_mm: float,
           image_width_mm: float = None, image_height_mm: float = None) -> Label:
    """
    Create a label preset that centers an image on the label.

    :param file_path: Path to the image file.
    :param label_width_mm: Label width in mm.
    :param label_height_mm: Label height in mm.
    :param image_width_mm: Optional image width in mm.
    :param image_height_mm: Optional image height in mm.
    :return: A Label object with the image centered.
    """
    with Image.open(file_path) as img:
        orig_width_mm = img.width / DPI * 25.4
        orig_height_mm = img.height / DPI * 25.4

    if image_width_mm is None:
        image_width_mm = orig_width_mm
    if image_height_mm is None:
        image_height_mm = orig_height_mm

    image_elem = ImageElement(
        file_path,
        width_mm=image_width_mm,
        height_mm=image_height_mm,
        center_horizontal=True,
        center_vertical=True
    )

    return Label(image_elem, width_mm=label_width_mm, height_mm=label_height_mm)
