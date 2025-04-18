# src/presets/image_label.py

import logging
from abc import ABC
from PIL import Image
from src.presets.base_label import BaseLabelPreset
from src.label import Label
from src.elements.image_element import ImageElement
from src.config import DPI

logger = logging.getLogger(__name__)


class ImageLabel(BaseLabelPreset):
    """
    Preset for labels containing a single, centered image.

    :param file_path: Path to the image file.
    :param label_width_mm: Label width in millimeters.
    :param label_height_mm: Label height in millimeters.
    :param image_width_mm: Desired image width in millimeters (optional).
    :param image_height_mm: Desired image height in millimeters (optional).
    """

    def __init__(
            self,
            file_path: str,
            label_width_mm: float,
            label_height_mm: float,
            image_width_mm: float = None,
            image_height_mm: float = None,
    ) -> None:
        logger.debug(
            "Initializing ImageLabel(file=%s, label_w=%.1fmm, label_h=%.1fmm, img_w=%smm, img_h=%smm)",
            file_path, label_width_mm, label_height_mm, image_width_mm, image_height_mm
        )

        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")

        self.file_path = file_path
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.image_width_mm = image_width_mm
        self.image_height_mm = image_height_mm

        # Determine original image size in mm if needed
        with Image.open(file_path) as img:
            self.orig_width_mm = img.width / DPI * 25.4
            self.orig_height_mm = img.height / DPI * 25.4

    def create_zpl(self) -> str:
        """
        Build and return the ZPL for this image label.
        """
        # fallback to original image dimensions if not overridden
        img_w = self.image_width_mm or self.orig_width_mm
        img_h = self.image_height_mm or self.orig_height_mm

        logger.debug(
            "Creating ImageElement with image_w=%.1fmm, image_h=%.1fmm",
            img_w, img_h
        )

        elem = ImageElement(
            file_path=self.file_path,
            width_mm=img_w,
            height_mm=img_h,
            center_horizontal=True,
            center_vertical=True,
        )
        # Label will render the element and wrap it in ^XA…^XZ
        label = Label(
            elem,
            width_mm=self.label_width_mm,
            height_mm=self.label_height_mm
        )
        return label.zpl
