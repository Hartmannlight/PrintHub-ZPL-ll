from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from PIL import Image

from .labelary import render_labelary_png
from .zpl import encode_field_data
from .zpl_2d import InkMetricsDots


ZplOrientation = Literal['N', 'R', 'I', 'B']

_MAX_LABEL_IN = 15.0

@dataclass(frozen=True)
class ZplFontSpec:
    font: str
    orientation: ZplOrientation = 'N'
    height: int | None = None
    width: int | None = None

    def to_zpl(self) -> str:
        if self.height is None or self.width is None:
            return f'^A{self.font}{self.orientation}'
        return f'^A{self.font}{self.orientation},{self.height},{self.width}'


def _normalize_text(text: str) -> str:
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    return normalized.replace('\n', '\\&')


def _ink_bbox(img: Image.Image, threshold: int) -> tuple[int, int, int, int] | None:
    if not (0 <= threshold <= 255):
        raise ValueError('threshold must be in [0..255]')

    if img.mode not in ('RGB', 'RGBA', 'L'):
        img = img.convert('RGBA')

    if img.mode == 'RGBA':
        background = Image.new('RGBA', img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img).convert('L')
    else:
        img = img.convert('L')

    mask = img.point(lambda p: 255 if p < threshold else 0, mode='L')
    return mask.getbbox()


class ZplTextMeasurer:
    def __init__(
        self,
        dpmm: int = 8,
        label_width_in: float = 4.0,
        label_height_in: float = 6.0,
        threshold: int = 250,
        max_attempts: int = 5,
        use_utf8: bool = True,
    ) -> None:
        if dpmm <= 0:
            raise ValueError('dpmm must be > 0')
        if label_width_in <= 0 or label_height_in <= 0:
            raise ValueError('label_width_in/label_height_in must be > 0')
        if max_attempts <= 0:
            raise ValueError('max_attempts must be > 0')

        self._dpmm = dpmm
        self._label_w_in = label_width_in
        self._label_h_in = label_height_in
        self._threshold = threshold
        self._max_attempts = max_attempts
        self._use_utf8 = use_utf8

    def build_zpl(self, text: str, font: ZplFontSpec, x: int = 0, y: int = 0) -> str:
        if x < 0 or y < 0:
            raise ValueError('x/y must be >= 0')

        normalized = _normalize_text(text)
        encoding = 'utf-8' if self._use_utf8 else 'ascii'
        needs_hex, fd = encode_field_data(normalized, hex_indicator='_', encoding=encoding)

        ci = '^CI28\n' if self._use_utf8 else ''
        fh = '^FH\n' if needs_hex else ''

        return (
            '^XA\n'
            f'{ci}'
            '^LH0,0\n'
            f'^FO{x},{y}\n'
            f'{font.to_zpl()}\n'
            f'{fh}'
            f'^FD{fd}^FS\n'
            '^XZ'
        )

    def measure(self, text: str, font: ZplFontSpec, x: int = 0, y: int = 0) -> InkMetricsDots:
        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / 'measure.png'
            return self.measure_and_render(text=text, font=font, out_path=out_path, x=x, y=y)

    def measure_and_render(
        self,
        text: str,
        font: ZplFontSpec,
        out_path: Path,
        x: int = 0,
        y: int = 0,
    ) -> InkMetricsDots:
        zpl = self.build_zpl(text=text, font=font, x=x, y=y)

        w_in = self._label_w_in
        h_in = self._label_h_in

        last_bbox: tuple[int, int, int, int] | None = None
        last_size: tuple[int, int] | None = None

        for _ in range(self._max_attempts):
            w_in = min(w_in, _MAX_LABEL_IN)
            h_in = min(h_in, _MAX_LABEL_IN)
            render_labelary_png(
                zpl=zpl,
                out_path=out_path,
                dpmm=self._dpmm,
                label_width_in=w_in,
                label_height_in=h_in,
            )

            with Image.open(out_path) as img:
                bbox = _ink_bbox(img, threshold=self._threshold)
                last_bbox = bbox
                last_size = (img.width, img.height)

            if bbox is None:
                return InkMetricsDots(ink_offset_x=0, ink_offset_y=0, ink_width=0, ink_height=0)

            left, top, right, bottom = bbox
            img_w, img_h = last_size

            if right < img_w - 1 and bottom < img_h - 1:
                return InkMetricsDots(
                    ink_offset_x=left,
                    ink_offset_y=top,
                    ink_width=right - left,
                    ink_height=bottom - top,
                )

            if w_in >= _MAX_LABEL_IN and h_in >= _MAX_LABEL_IN:
                return InkMetricsDots(
                    ink_offset_x=left,
                    ink_offset_y=top,
                    ink_width=right - left,
                    ink_height=bottom - top,
                )

            w_in *= 2.0
            h_in *= 2.0

        raise RuntimeError(
            'Text did not fit into the rendered label. '
            f'Last bbox={last_bbox}, last_image_size={last_size}, '
            f'final_label_size_in=({w_in}x{h_in}).'
        )
