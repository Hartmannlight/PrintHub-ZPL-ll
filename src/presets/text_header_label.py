# src/presets/text_header_label.py
import logging
from src.presets.base_label import BaseLabelPreset
from src.utils.zpl_element_measurer import ZPLElementMeasurer
from src.utils.conversion import mm_to_pixels
from src.config import DPI, DEFAULT_FONT

logger = logging.getLogger(__name__)


class TextHeaderLabel(BaseLabelPreset):
    """
    Preset for header/body labels with underline under the header.
    """

    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        header_text: str,
        content_text: str,
        header_font_size: int = 30,
        content_font_size: int = 20,
        underline_thickness: int = 2,
        padding_mm: float = 2.0,
    ) -> None:
        """
        :param label_width_mm: width in mm (>0)
        :param label_height_mm: height in mm (>0)
        :param header_text: Header string
        :param content_text: Body text
        :param header_font_size: Font size for header
        :param content_font_size: Font size for body
        :param underline_thickness: Thickness of underline
        :param padding_mm: Padding around text in mm
        :raises ValueError: If dimensions are not positive
        """
        logger.debug("Initializing TextHeaderLabel(width=%.1f, height=%.1f, header=%r)", label_width_mm, label_height_mm, header_text)
        if label_width_mm <= 0 or label_height_mm <= 0:
            raise ValueError("Label dimensions must be positive")
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.header_text = header_text
        self.content_text = content_text
        self.header_font_size = header_font_size
        self.content_font_size = content_font_size
        self.underline_thickness = underline_thickness
        self.padding_px = mm_to_pixels(padding_mm, DPI)

    def create_zpl(self) -> str:
        """
        Generate ZPL for the header/body label.

        :return: ZPL code as string.
        """
        logger.debug("Starting create_zpl for TextHeaderLabel")
        label_w_px = mm_to_pixels(self.label_width_mm, DPI)
        label_h_px = mm_to_pixels(self.label_height_mm, DPI)
        measurer = ZPLElementMeasurer.default()

        # Measure header
        hdr_zpl = f"^XA^CI28^FO0,0^A{DEFAULT_FONT},{self.header_font_size}^FD{self.header_text}^FS^XZ"
        hdr_w, hdr_h, hdr_top = measurer.measure_zpl(hdr_zpl)
        total_hdr_h = hdr_h + hdr_top + self.padding_px

        # Measure body
        body_zpl = f"^XA^CI28^FO0,0^A{DEFAULT_FONT},{self.content_font_size}^FD{self.content_text}^FS^XZ"
        body_w, body_h, _ = measurer.measure_zpl(body_zpl)

        parts = ["^XA", "^CI28"]
        # Header
        x_hdr = (label_w_px - hdr_w) // 2
        y_hdr = self.padding_px + hdr_top
        parts.append(f"^FO{x_hdr},{y_hdr}^A{DEFAULT_FONT},{self.header_font_size}^FD{self.header_text}^FS")
        # Underline
        y_line = y_hdr + hdr_h + 1
        parts.append(f"^FO{x_hdr},{y_line}^GB{hdr_w},{self.underline_thickness},{self.underline_thickness}^FS")
        # Body
        x_body = (label_w_px - body_w) // 2
        y_body = y_line + self.underline_thickness + self.padding_px
        parts.append(f"^FO{x_body},{y_body}^A{DEFAULT_FONT},{self.content_font_size}^FD{self.content_text}^FS")
        parts.append("^XZ")

        return "\n".join(parts)
