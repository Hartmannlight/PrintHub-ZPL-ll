from __future__ import annotations

import math
from dataclasses import dataclass
import os

from .zpl_text_metrics import ZplFontSpec, ZplTextMeasurer


@dataclass(frozen=True)
class TextMetrics:
    lines: int
    width_dots: int
    height_dots: int


class TextMeasurer:
    def estimate(self, *, text: str, box_width_dots: int, font_height_dots: int, font_width_dots: int, wrap: str, line_spacing_dots: int) -> TextMetrics:
        raise NotImplementedError


class MonospaceApproxMeasurer(TextMeasurer):
    def estimate(self, *, text: str, box_width_dots: int, font_height_dots: int, font_width_dots: int, wrap: str, line_spacing_dots: int) -> TextMetrics:
        if box_width_dots <= 0 or font_width_dots <= 0 or font_height_dots <= 0:
            return TextMetrics(lines=0, width_dots=0, height_dots=0)

        char_w = max(1, int(font_width_dots * 0.6))
        line_h = font_height_dots + line_spacing_dots
        max_chars = max(1, box_width_dots // char_w)

        normalized = text.replace('\r\n', '\n').replace('\r', '\n')
        paragraphs = normalized.split('\n')
        lines = 0
        for p in paragraphs:
            p = p.strip()
            if not p:
                lines += 1
                continue
            if wrap == 'none':
                lines += 1
                continue
            if wrap == 'char':
                lines += int(math.ceil(len(p) / max_chars))
                continue
            lines += _estimate_word_wrap_lines(p, max_chars)

        width = min(box_width_dots, max_chars * char_w)
        height = lines * line_h
        return TextMetrics(lines=lines, width_dots=width, height_dots=height)


class ZplMeasuredTextMeasurer(TextMeasurer):
    _CHAR_WRAP_WIDTH_RATIO = 0.45
    def __init__(
        self,
        dpmm: int = 8,
        label_width_in: float = 4.0,
        label_height_in: float = 6.0,
        threshold: int = 250,
        max_attempts: int = 5,
        use_utf8: bool = True,
        enable_network: bool | None = None,
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
        if enable_network is None:
            enable_network = os.getenv('LABELARY_ENABLE', '0') == '1'
        self._enable_network = enable_network
        self._width_cache: dict[tuple[str, int, int], int] = {}

    def for_dpi(self, dpi: int) -> 'ZplMeasuredTextMeasurer':
        dpmm = int(round(dpi / 25.4))
        return ZplMeasuredTextMeasurer(
            dpmm=dpmm,
            label_width_in=self._label_w_in,
            label_height_in=self._label_h_in,
            threshold=self._threshold,
            max_attempts=self._max_attempts,
            use_utf8=self._use_utf8,
            enable_network=self._enable_network,
        )

    def wrap_lines(
        self,
        *,
        text: str,
        box_width_dots: int,
        font_height_dots: int,
        font_width_dots: int,
        wrap: str,
    ) -> list[str]:
        if box_width_dots <= 0:
            return [text]

        paragraphs = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        lines: list[str] = []
        for paragraph in paragraphs:
            if paragraph == '':
                lines.append('')
                continue
            if wrap == 'none':
                lines.append(paragraph)
                continue
            if wrap == 'char':
                lines.extend(self._wrap_char(paragraph, box_width_dots, font_height_dots, font_width_dots))
            else:
                lines.extend(self._wrap_word(paragraph, box_width_dots, font_height_dots, font_width_dots))
        return lines or ['']

    def measure_wrapped(
        self,
        *,
        lines: list[str],
        font_height_dots: int,
        font_width_dots: int,
        line_spacing_dots: int,
    ) -> TextMetrics:
        font = ZplFontSpec(font='0', orientation='N', height=font_height_dots, width=font_width_dots)
        if not self._enable_network:
            char_w = max(1, int(font_width_dots * 0.6))
            max_chars = max((len(line) for line in lines), default=0)
            width = max_chars * char_w
            height = len(lines) * (font_height_dots + line_spacing_dots)
            return TextMetrics(lines=len(lines), width_dots=width, height_dots=height)
        max_line_width = 1
        for line in lines:
            width = self._line_width(line, font_height_dots, font_width_dots)
            if width > max_line_width:
                max_line_width = width
        measurer = self._make_measurer(box_width_dots=max_line_width, font_height_dots=font_height_dots)
        text = '\n'.join(lines)
        ink = measurer.measure(text=text, font=font)
        extra_spacing = max(0, len(lines) - 1) * max(0, line_spacing_dots)
        height = ink.ink_height + extra_spacing
        return TextMetrics(lines=len(lines), width_dots=ink.ink_width, height_dots=height)

    def estimate(
        self,
        *,
        text: str,
        box_width_dots: int,
        font_height_dots: int,
        font_width_dots: int,
        wrap: str,
        line_spacing_dots: int,
    ) -> TextMetrics:
        lines = self.wrap_lines(
            text=text,
            box_width_dots=box_width_dots,
            font_height_dots=font_height_dots,
            font_width_dots=font_width_dots,
            wrap=wrap,
        )
        return self.measure_wrapped(
            lines=lines,
            font_height_dots=font_height_dots,
            font_width_dots=font_width_dots,
            line_spacing_dots=line_spacing_dots,
        )

    def _wrap_word(self, text: str, box_width_dots: int, font_height_dots: int, font_width_dots: int) -> list[str]:
        words = [w for w in text.split() if w]
        if not words:
            return ['']

        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f'{current} {word}'
            if self._line_width(candidate, font_height_dots, font_width_dots) <= box_width_dots:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _wrap_char(self, text: str, box_width_dots: int, font_height_dots: int, font_width_dots: int) -> list[str]:
        remaining = text
        lines: list[str] = []
        def should_hyphenate(prev_char: str, next_char: str) -> bool:
            if not prev_char or not next_char:
                return False
            if prev_char.isspace() or next_char.isspace():
                return False
            return prev_char.isalnum() and next_char.isalnum()

        if not self._enable_network:
            char_w = max(1, int(font_width_dots * self._CHAR_WRAP_WIDTH_RATIO))
            max_len = max(1, box_width_dots // char_w)
            while remaining:
                if max_len >= len(remaining):
                    lines.append(remaining)
                    break
                line = remaining[:max_len]
                next_char = remaining[max_len]
                if should_hyphenate(line[-1], next_char) and max_len > 2:
                    prefix = remaining[:max_len - 1]
                    suffix_len = len(remaining) - (max_len - 1)
                    if (
                        prefix
                        and prefix == prefix.strip()
                        and prefix.isalnum()
                        and len(prefix) >= 2
                        and suffix_len >= 2
                    ):
                        line = prefix + '-'
                        remaining = remaining[max_len - 1:]
                    else:
                        remaining = remaining[max_len:]
                else:
                    remaining = remaining[max_len:]
                lines.append(line)
            return lines or ['']

        while remaining:
            max_len = self._max_chars_that_fit(remaining, box_width_dots, font_height_dots, font_width_dots)
            if max_len <= 0:
                lines.append(remaining)
                break
            if max_len >= len(remaining):
                lines.append(remaining)
                break
            line = remaining[:max_len]
            next_char = remaining[max_len]
            if should_hyphenate(line[-1], next_char) and max_len > 2:
                prefix = remaining[:max_len - 1]
                suffix_len = len(remaining) - (max_len - 1)
                if (
                    prefix
                    and prefix == prefix.strip()
                    and prefix.isalnum()
                    and len(prefix) >= 2
                    and suffix_len >= 2
                ):
                    line = prefix + '-'
                    remaining = remaining[max_len - 1:]
                else:
                    remaining = remaining[max_len:]
            else:
                remaining = remaining[max_len:]
            lines.append(line)
        return lines or ['']

    def _max_chars_that_fit(self, text: str, box_width_dots: int, font_height_dots: int, font_width_dots: int) -> int:
        low = 1
        high = len(text)
        best = 0
        while low <= high:
            mid = (low + high) // 2
            if self._line_width(text[:mid], font_height_dots, font_width_dots) <= box_width_dots:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _line_width(self, text: str, font_height_dots: int, font_width_dots: int) -> int:
        key = (text, font_height_dots, font_width_dots)
        cached = self._width_cache.get(key)
        if cached is not None:
            return cached

        if not self._enable_network:
            char_w = max(1, int(font_width_dots * 0.6))
            width = len(text) * char_w
            self._width_cache[key] = width
            return width

        font = ZplFontSpec(font='0', orientation='N', height=font_height_dots, width=font_width_dots)
        measurer = self._make_measurer(box_width_dots=max(1, font_width_dots), font_height_dots=font_height_dots)
        ink = measurer.measure(text=text, font=font)
        width = ink.ink_width
        self._width_cache[key] = width
        return width

    def _make_measurer(self, *, box_width_dots: int, font_height_dots: int) -> ZplTextMeasurer:
        dpmm = self._dpmm
        width_in = max(self._label_w_in, box_width_dots / (dpmm * 25.4))
        height_in = max(self._label_h_in, max(1, font_height_dots) / (dpmm * 25.4))
        return ZplTextMeasurer(
            dpmm=dpmm,
            label_width_in=width_in,
            label_height_in=height_in,
            threshold=self._threshold,
            max_attempts=self._max_attempts,
            use_utf8=self._use_utf8,
        )


def _estimate_word_wrap_lines(text: str, max_chars: int) -> int:
    words = [w for w in text.split() if w]
    if not words:
        return 1
    lines = 1
    current = 0
    for w in words:
        wlen = len(w)
        if current == 0:
            current = wlen
            continue
        if current + 1 + wlen <= max_chars:
            current += 1 + wlen
        else:
            lines += 1
            current = wlen
    return lines
