import logging
from src.presets.base import BaseLabelPreset
from src.utils.zpl_element_measurer import ZPLElementMeasurer
from src.utils.conversion import mm_to_pixels
from src.config import DPI, DEFAULT_FONT

logger = logging.getLogger(__name__)


class TextHeaderLabel(BaseLabelPreset):
    def __init__(
        self,
        label_width_mm: float,
        label_height_mm: float,
        header_text: str,
        content_text: str,
        header_font_size: int = 30,
        content_font_size: int = 20,
        header_center_horizontal: bool = True,
        content_center_horizontal: bool = True,
        underline_thickness: int = 2,
        padding_mm: float = 2.0
    ) -> None:
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.header_text = header_text
        self.content_text = content_text
        self.header_font_size = header_font_size
        self.content_font_size = content_font_size
        self.header_center_horizontal = header_center_horizontal
        self.content_center_horizontal = content_center_horizontal
        self.underline_thickness = underline_thickness
        self.padding_px = mm_to_pixels(padding_mm, DPI)

    def create_zpl(self) -> str:
        # Label in Pixel
        label_w_px = mm_to_pixels(self.label_width_mm, DPI)
        label_h_px = mm_to_pixels(self.label_height_mm, DPI)

        measurer = ZPLElementMeasurer.default()

        # --- 1) Header messen ---
        temp_header_zpl = (
            "^XA"
            "^CI28"  # UTF‑8 aktivieren
            f"^FO0,0^A{DEFAULT_FONT},{self.header_font_size}^FD{self.header_text}^FS"
            "^XZ"
        )
        header_w_px, header_h_px, header_top_pad = measurer.measure_zpl(temp_header_zpl)
        # tatsächliche Höhe inklusive Padding
        header_total_h_px = header_h_px + header_top_pad + self.padding_px

        # --- 2) Body messen (für horizontale Zentrierung) ---
        temp_body_zpl = (
            "^XA"
            "^CI28"
            f"^FO0,0^A{DEFAULT_FONT},{self.content_font_size}^FD{self.content_text}^FS"
            "^XZ"
        )
        body_w_px, body_h_px, body_top_pad = measurer.measure_zpl(temp_body_zpl)

        # --- 3) ZPL zusammenbauen ---
        parts = ["^XA", "^CI28"]  # Start + UTF‑8

        # 3.1 Header-Text
        if self.header_center_horizontal:
            x_hdr = (label_w_px - header_w_px) // 2
        else:
            x_hdr = self.padding_px
        y_hdr = self.padding_px + header_top_pad
        parts.append(f"^FO{x_hdr},{y_hdr}^A{DEFAULT_FONT},{self.header_font_size}^FD{self.header_text}^FS")

        # 3.2 Unterstreichung exakt so breit wie der Header-Text
        line_y = y_hdr + header_h_px + 1  # direkt unter die Buchstaben
        parts.append(
            f"^FO{x_hdr},{line_y}"
            f"^GB{header_w_px},{self.underline_thickness},{self.underline_thickness}^FS"
        )

        # 3.3 Body-Text
        if self.content_center_horizontal:
            x_body = (label_w_px - body_w_px) // 2
        else:
            x_body = self.padding_px
        # Body unterhalb von Header + Padding
        y_body = line_y + self.underline_thickness + self.padding_px
        parts.append(
            f"^FO{x_body},{y_body}^A{DEFAULT_FONT},{self.content_font_size}^FD{self.content_text}^FS"
        )

        parts.append("^XZ")
        return "\n".join(parts)
