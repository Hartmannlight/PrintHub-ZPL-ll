from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class ZplOptions:
    emit_ci28: bool = False


class ZplBuilder:
    def __init__(self, *, options: Optional[ZplOptions] = None):
        self._lines: list[str] = []
        self._options = options or ZplOptions()
        self._origin_x = 0
        self._origin_y = 0

    def start_label(self, *, width_dots: int, height_dots: int, origin_x: int = 0, origin_y: int = 0) -> None:
        self._origin_x = origin_x
        self._origin_y = origin_y
        self._lines.append('^XA')
        self._lines.append(f'^PW{width_dots}')
        self._lines.append(f'^LL{height_dots}')
        self._lines.append(f'^LH{origin_x},{origin_y}')
        if self._options.emit_ci28:
            self._lines.append('^CI28')

    def end_label(self) -> None:
        self._lines.append('^XZ')

    def field_origin(self, x: int, y: int) -> None:
        self._lines.append(f'^FO{x},{y}')

    def label_home_offset(self, *, dx: int = 0, dy: int = 0) -> None:
        x = self._origin_x + dx
        y = self._origin_y + dy
        self._lines.append(f'^LH{x},{y}')

    def field_separator(self) -> None:
        self._lines.append('^FS')

    def font_a0(self, *, height: int, width: int) -> None:
        self._lines.append(f'^A0N,{height},{width}')

    def field_block(self, *, width: int, max_lines: int, line_spacing: int, justification: str, hanging_indent: int = 0) -> None:
        self._lines.append(f'^FB{width},{max_lines},{line_spacing},{justification},{hanging_indent}')

    def field_hex(self, indicator: str = '_') -> None:
        if indicator == '_':
            self._lines.append('^FH')
        else:
            self._lines.append(f'^FH{indicator}')

    def field_data(self, data: str) -> None:
        self._lines.append(f'^FD{data}')

    def qr_code(self, *, model: int, magnification: int) -> None:
        self._lines.append(f'^BQN,{model},{magnification}')

    def datamatrix(self, *, module_size: int, quality: int, columns: int, rows: int, format_id: int, escape_char: str) -> None:
        esc = escape_char if escape_char else '_'
        self._lines.append(f'^BXN,{module_size},{quality},{columns},{rows},{format_id},{esc}')

    def graphic_box(self, *, width: int, height: int, thickness: int, color: str = 'B', rounding: int = 0) -> None:
        self._lines.append(f'^GB{width},{height},{thickness},{color},{rounding}')

    def graphic_field(self, *, total_bytes: int, bytes_per_row: int, data: str) -> None:
        self._lines.append(f'^GFA,{total_bytes},{total_bytes},{bytes_per_row},{data}')

    def build(self) -> str:
        return ''.join(line + '\n' for line in self._lines)


def encode_field_data(text: str, *, hex_indicator: str = '_', encoding: str = 'utf-8') -> tuple[bool, str]:
    safe_ascii = set(range(0x20, 0x7F))
    raw = text.encode(encoding, errors='strict')

    needs_hex = False
    out_chars: list[str] = []

    for b in raw:
        if b in safe_ascii and b not in (0x5E, 0x7E):
            ch = chr(b)
            if ch == hex_indicator:
                needs_hex = True
                out_chars.append(f'{hex_indicator}5F')
            else:
                out_chars.append(ch)
        else:
            needs_hex = True
            out_chars.append(f'{hex_indicator}{b:02X}')

    return needs_hex, ''.join(out_chars)
