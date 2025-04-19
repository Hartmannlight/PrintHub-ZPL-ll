import logging
from typing import List, Tuple
from src.elements.elements import Element, DEFAULT_LINE_PADDING
from src.utils.zpl_element_measurer import ZPLElementMeasurer
from src.config import DEFAULT_FONT, DEFAULT_FONT_SIZE

logger = logging.getLogger(__name__)


class TextElement(Element):
    """
    Represents a text element in a label. Supports multi-line text.
    """

    def __init__(self, text: str, x: int = 0, y: int = 0,
                 font: str = DEFAULT_FONT, font_size: int = DEFAULT_FONT_SIZE,
                 center_horizontal: bool = False,
                 center_vertical: bool = False) -> None:
        """
        Initialize a TextElement.

        :param text: The text content.
        :param x: X-coordinate.
        :param y: Y-coordinate.
        :param font: Font identifier.
        :param font_size: Font size.
        :param center_horizontal: Flag to center horizontally.
        :param center_vertical: Flag to center vertically.
        """
        logger.debug("Creating TextElement with text: %s", text)
        self.text = text
        self.x = x
        self.y = y
        self.font = font
        self.font_size = font_size
        self.center_horizontal = center_horizontal
        self.center_vertical = center_vertical

    def _generate_multiline_zpl(self, label: "Label", offset_x: int = 0,
                                  offset_y: int = 0) -> str:
        """
        Generate ZPL code for multi-line text.

        :param label: The parent label.
        :param offset_x: Horizontal offset.
        :param offset_y: Vertical offset.
        :return: ZPL code as a string.
        """
        measurer: ZPLElementMeasurer = label.measurer
        lines = self.text.splitlines()
        measurements: List[Tuple[int, int, int]] = [
            measurer.measure_zpl(f"^XA^FO0,0^A{self.font},{self.font_size}^FD{line}^FS^XZ")
            for line in lines
        ]

        total_height = measurements[0][1]
        for i in range(1, len(measurements)):
            line_top = max(DEFAULT_LINE_PADDING, measurements[i][2])
            total_height += line_top + (measurements[i][1] - measurements[i][2])

        base_y = int((label.height_px - total_height) / 2 + self.y) if self.center_vertical else self.y

        zpl_lines: List[str] = []
        current_y = base_y
        for i, line in enumerate(lines):
            width, height, top_pad = measurer.measure_zpl(
                f"^XA^FO0,0^A{self.font},{self.font_size}^FD{line}^FS^XZ"
            )
            base_x = int((label.width_px - width) / 2 + self.x) if self.center_horizontal else self.x
            final_x = max(base_x + offset_x, 0)
            final_y = max(int(current_y) + offset_y, 0)
            zpl_line = f"^FO{final_x},{final_y}^A{self.font},{self.font_size}^FD{line}^FS"
            logger.debug("Text line ZPL: %s", zpl_line)
            zpl_lines.append(zpl_line)
            if i < len(lines) - 1:
                next_pad = max(DEFAULT_LINE_PADDING, measurements[i + 1][2])
                current_y += next_pad + (height - top_pad)
        return "\n".join(zpl_lines)

    def to_zpl(self, label: "Label", offset_x: int = 0, offset_y: int = 0) -> str:
        measurer: ZPLElementMeasurer = label.measurer
        converted_text = self.text

        if "\n" in self.text:
            zpl_code = self._generate_multiline_zpl(label, offset_x, offset_y)
            logger.debug("Multiline TextElement ZPL: %s", zpl_code)
            return zpl_code
        else:
            final_x, final_y = self.x, self.y
            if self.center_horizontal or self.center_vertical:
                width, height, _ = measurer.measure_zpl(f"^XA^FO0,0^A{self.font},{self.font_size}^FD{converted_text}^FS^XZ")
                if self.center_horizontal:
                    final_x = int((label.width_px - width) / 2 + self.x)
                if self.center_vertical:
                    final_y = int((label.height_px - height) / 2 + self.y)
            final_x = max(final_x + offset_x, 0)
            final_y = max(final_y + offset_y, 0)
            zpl_code = f"^FO{final_x},{final_y}^A{self.font},{self.font_size}^FD{converted_text}^FS"
            logger.debug("Single line TextElement ZPL: %s", zpl_code)
            return zpl_code
