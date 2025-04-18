# src/presets/text.py
import logging
from src.presets.base import BaseLabelPreset
from src.elements.text_element import TextElement
from src.label import Label
from src.config import DEFAULT_FONT, DEFAULT_FONT_SIZE

logger = logging.getLogger(__name__)


class TextLabel(BaseLabelPreset):
    """
    Preset for simple text labels: centers the provided content.
    """

    def __init__(self, content: str, font: str = DEFAULT_FONT, label_width_mm: float = 70, label_height_mm: float = 100) -> None:
        """
        :param content: Text content
        :param font: Font identifier
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing TextLabel(content=%r, font=%r, width=%.1f, height=%.1f)", content, font, label_width_mm, label_height_mm)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.content = content
        self.font = font
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the text label.

        :return: ZPL code as a string.
        """
        logger.debug("Starting create_zpl for TextLabel")
        elem = TextElement(text=self.content, font=self.font, font_size=DEFAULT_FONT_SIZE, center_horizontal=True, center_vertical=True)
        return Label(elem, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl
