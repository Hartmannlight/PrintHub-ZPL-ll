from src.label import Label
from src.elements.text_element import TextElement
from src.config import DEFAULT_FONT, DEFAULT_FONT_SIZE
from src.presets.base import BaseLabelPreset

class TextLabel(BaseLabelPreset):
    """
    Text Label preset.

    Creates a label with centered text.
    """

    def __init__(self, content: str, font: str = DEFAULT_FONT,
                 label_width_mm: float = 70, label_height_mm: float = 100) -> None:
        """
        Initialize a TextLabel.

        :param content: The text content.
        :param font: Font identifier.
        :param label_width_mm: Label width in mm.
        :param label_height_mm: Label height in mm.
        """
        self.content = content
        self.font = font
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm

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
        # Verwende nun die übergebenen Dimensionen statt fest kodierter Werte
        return Label(centered_text, width_mm=self.label_width_mm, height_mm=self.label_height_mm).zpl
