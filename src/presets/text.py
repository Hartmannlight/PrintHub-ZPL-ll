from src.label import Label
from src.elements.text_element import TextElement
from src.config import DEFAULT_FONT, DEFAULT_FONT_SIZE
from src.presets.base import BaseLabelPreset


class TextLabel(BaseLabelPreset):
    """
    Text Label preset.

    Creates a label with centered text.
    """

    def __init__(self, content: str, font: str = DEFAULT_FONT) -> None:
        """
        Initialize a TextLabel.

        :param content: The text content.
        :param font: Font identifier.
        """
        self.content = content
        self.font = font

    def create_zpl(self) -> str:
        """
        Generate ZPL code for the text label.

        :return: ZPL code as a string.
        """
        centered_text = TextElement(
            text=self.content,
            font=self.font,
            font_size=DEFAULT_FONT_SIZE,
            center_horizontal=True,
            center_vertical=True
        )
        return Label(centered_text, width_mm=70, height_mm=100).zpl
