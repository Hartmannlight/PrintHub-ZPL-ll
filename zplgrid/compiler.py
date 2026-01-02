from __future__ import annotations

from dataclasses import dataclass
import base64
import io
import os
import warnings
from typing import Any, Mapping, Optional

from .exceptions import CompilationError
from .layout import compute_layout
from .measure import TextMeasurer, ZplMeasuredTextMeasurer
from .model import DataMatrixElement, ImageElement, LeafNode, LabelTarget, LineElement, QrElement, Template, TextElement
from .render import RenderOptions, render_text
from .units import clamp_int, mm_to_dots
from .zpl import ZplBuilder, ZplOptions, encode_field_data
from .zpl_2d import DataMatrixZplBuilder, QrCodeZplBuilder


def compile_zpl(template_json: str | bytes | Mapping[str, Any], *, target: LabelTarget, variables: Optional[Mapping[str, Any]] = None, debug: bool = False) -> str:
    from .parser import load_template
    template = load_template(template_json)
    return template.compile(target=target, variables=variables or {}, debug=debug)


@dataclass
class Compiler:
    text_measurer: TextMeasurer = ZplMeasuredTextMeasurer()

    def compile(self, template: Template, *, target: LabelTarget, variables: Mapping[str, Any], debug: bool = False) -> str:
        width_dots = mm_to_dots(target.width_mm, target.dpi)
        height_dots = mm_to_dots(target.height_mm, target.dpi)
        origin_x = mm_to_dots(target.origin_x_mm, target.dpi)
        origin_y = mm_to_dots(target.origin_y_mm, target.dpi)

        render_defaults = template.defaults.render_defaults
        render_opts = RenderOptions(missing_variables=str(render_defaults.get('missing_variables', 'error')))
        zpl_opts = ZplOptions(emit_ci28=bool(template.defaults.render_defaults.get('emit_ci28', False)))
        debug_padding_guides = bool(render_defaults.get('debug_padding_guides', False))
        debug_gutter_guides = bool(render_defaults.get('debug_gutter_guides', False))

        layout = compute_layout(template.layout, width_dots=width_dots, height_dots=height_dots, dpi=target.dpi)

        z = ZplBuilder(options=zpl_opts)
        z.start_label(width_dots=width_dots, height_dots=height_dots, origin_x=origin_x, origin_y=origin_y)

        for divider in layout.dividers:
            if divider.rect.w <= 0 or divider.rect.h <= 0:
                continue
            thickness = max(1, divider.thickness)
            z.field_origin(divider.rect.x, divider.rect.y)
            z.graphic_box(width=divider.rect.w, height=divider.rect.h, thickness=thickness, color='B', rounding=0)
            z.field_separator()

        if debug_gutter_guides:
            for gutter in layout.gutters:
                self._emit_gutter_guide(z, rect=gutter.rect, direction=gutter.direction)

        for leaf in layout.leaves:
            if debug or leaf.node.debug_border:
                self._emit_border(z, leaf.rect)
            if debug_padding_guides:
                self._emit_padding_guide(z, leaf.content_rect)

            element = leaf.node.elements[0]
            element_box = self._compute_element_box(element=element, rect=leaf.content_rect, dpi=target.dpi)

            if isinstance(element, TextElement):
                self._emit_text(z, element=element, rect=element_box, variables=variables, render_opts=render_opts, dpi=target.dpi)
            elif isinstance(element, QrElement):
                self._emit_qr(z, element=element, rect=element_box, variables=variables, render_opts=render_opts, dpi=target.dpi)
            elif isinstance(element, DataMatrixElement):
                self._emit_datamatrix(z, element=element, rect=element_box, variables=variables, render_opts=render_opts, dpi=target.dpi)
            elif isinstance(element, ImageElement):
                self._emit_image(z, element=element, rect=element_box, variables=variables, render_opts=render_opts, dpi=target.dpi)
            elif isinstance(element, LineElement):
                self._emit_line(z, element=element, rect=element_box, dpi=target.dpi)
            else:
                raise CompilationError(f'unsupported element type: {element.type!r}')

        z.end_label()
        return z.build()

    def _emit_border(self, z: ZplBuilder, rect) -> None:
        t = 1
        z.field_origin(rect.x, rect.y)
        z.graphic_box(width=max(1, rect.w), height=max(1, rect.h), thickness=t, color='B', rounding=0)
        z.field_separator()

    def _emit_padding_guide(self, z: ZplBuilder, rect) -> None:
        t = 1
        z.field_origin(rect.x, rect.y)
        z.graphic_box(width=max(1, rect.w), height=max(1, rect.h), thickness=t, color='B', rounding=0)
        z.field_separator()

    def _emit_gutter_guide(self, z: ZplBuilder, *, rect, direction: str) -> None:
        t = 1
        z.field_origin(rect.x, rect.y)
        z.graphic_box(width=max(1, rect.w), height=max(1, rect.h), thickness=t, color='B', rounding=0)
        z.field_separator()

    def _compute_element_box(self, *, element, rect, dpi: int):
        pad = element.padding_mm
        left = mm_to_dots(pad.left, dpi)
        top = mm_to_dots(pad.top, dpi)
        right = mm_to_dots(pad.right, dpi)
        bottom = mm_to_dots(pad.bottom, dpi)
        box = rect.inset(left=left, top=top, right=right, bottom=bottom)

        if element.min_size_mm is not None:
            min_w = mm_to_dots(element.min_size_mm[0], dpi)
            min_h = mm_to_dots(element.min_size_mm[1], dpi)
            if box.w < min_w or box.h < min_h:
                raise CompilationError(f'element {element.type} does not meet min_size_mm: need {min_w}x{min_h} dots, got {box.w}x{box.h}')

        if element.max_size_mm is not None:
            max_w = mm_to_dots(element.max_size_mm[0], dpi)
            max_h = mm_to_dots(element.max_size_mm[1], dpi)
            target_w = min(box.w, max_w)
            target_h = min(box.h, max_h)
            dx = (box.w - target_w) // 2
            dy = (box.h - target_h) // 2
            box = type(box)(x=box.x + dx, y=box.y + dy, w=target_w, h=target_h)

        return box

    def _emit_text(self, z: ZplBuilder, *, element: TextElement, rect, variables: Mapping[str, Any], render_opts: RenderOptions, dpi: int) -> None:
        raw_text = render_text(element.text, variables, options=render_opts)
        raw_text = raw_text.replace('\r\n', '\n').replace('\r', '\n')
        raw_text = raw_text.replace('\\n', '\n')

        font_h_mm = element.font_height_mm
        if font_h_mm is None:
            font_h_mm = float(element.extensions.get('font_height_mm', 0.0)) if element.extensions else 0.0
        if not font_h_mm:
            font_h_mm = float(4.0)

        font_w_mm = element.font_width_mm or font_h_mm
        font_h = max(1, mm_to_dots(float(font_h_mm), dpi))
        font_w = max(1, mm_to_dots(float(font_w_mm), dpi))

        wrap = element.wrap or 'word'
        fit = element.fit or ('wrap' if wrap != 'none' else 'overflow')
        max_lines = int(element.max_lines or 9999)
        align_h = element.align_h or 'left'
        align_v = element.align_v or 'center'

        justification = {'left': 'L', 'center': 'C', 'right': 'R'}[align_h]
        line_spacing = 0

        box_x = rect.x
        box_y = rect.y

        explicit_lines = raw_text.split('\n')
        explicit_line_count = len(explicit_lines)
        explicit_lines_overflow = max_lines < 9999 and explicit_line_count > max_lines
        wrap_for_layout = wrap
        wrap_for_shrink = wrap
        if fit == 'shrink_to_fit' and wrap_for_layout == 'char':
            wrap_for_shrink = 'word'
        if fit == 'shrink_to_fit' and explicit_lines_overflow:
            wrap_for_layout = 'none'
            wrap_for_shrink = 'none'
            warnings.warn(
                f'Text element exceeds max_lines ({explicit_line_count} > {max_lines}); '
                'preserving explicit line breaks and ignoring max_lines for them.',
                stacklevel=2,
            )

        measurer = self._text_measurer_for_dpi(dpi)
        if fit == 'shrink_to_fit':
            shrink_max_lines = explicit_line_count if explicit_lines_overflow else max_lines
            font_h, font_w = self._shrink_text(
                text=raw_text,
                rect=rect,
                font_h=font_h,
                font_w=font_w,
                wrap=wrap_for_shrink,
                max_lines=shrink_max_lines,
                line_spacing=line_spacing,
                measurer=measurer,
            )

        layout_lines: list[str] | None = None
        if isinstance(measurer, ZplMeasuredTextMeasurer):
            layout_lines = measurer.wrap_lines(
                text=raw_text,
                box_width_dots=rect.w,
                font_height_dots=font_h,
                font_width_dots=font_w,
                wrap=wrap_for_layout,
            )
            if fit == 'truncate':
                layout_lines = layout_lines[:max_lines]

        if align_v in ('center', 'bottom'):
            if layout_lines is not None and isinstance(measurer, ZplMeasuredTextMeasurer):
                metrics = measurer.measure_wrapped(
                    lines=layout_lines,
                    font_height_dots=font_h,
                    font_width_dots=font_w,
                    line_spacing_dots=line_spacing,
                )
            else:
                metrics = measurer.estimate(
                    text=raw_text,
                    box_width_dots=rect.w,
                    font_height_dots=font_h,
                    font_width_dots=font_w,
                    wrap=wrap_for_layout,
                    line_spacing_dots=line_spacing,
                )
            content_h = metrics.height_dots
            if align_v == 'center':
                box_y = rect.y + max(0, (rect.h - content_h) // 2)
            else:
                box_y = rect.y + max(0, rect.h - content_h)

        text = raw_text.replace('\n', '\\&')
        if layout_lines is not None:
            text = '\\&'.join(layout_lines)

        z.field_origin(box_x, box_y)
        z.font_a0(height=font_h, width=font_w)

        if wrap != 'none' or fit in ('wrap', 'truncate', 'shrink_to_fit'):
            width = max(1, rect.w)
            fb_max_lines = max_lines
            if fit == 'shrink_to_fit' and explicit_lines_overflow:
                fb_max_lines = explicit_line_count
            if fit == 'overflow':
                fb_max_lines = 9999
            z.field_block(width=width, max_lines=fb_max_lines, line_spacing=line_spacing, justification=justification, hanging_indent=0)

        needs_hex, encoded = encode_field_data(text, hex_indicator='_', encoding='utf-8')
        if needs_hex:
            z.field_hex('_')
        z.field_data(encoded)
        z.field_separator()

    def _shrink_text(
        self,
        *,
        text: str,
        rect,
        font_h: int,
        font_w: int,
        wrap: str,
        max_lines: int,
        line_spacing: int,
        measurer: TextMeasurer,
    ) -> tuple[int, int]:
        if rect.w <= 0 or rect.h <= 0:
            return (font_h, font_w)

        current_h = font_h
        current_w = font_w
        for _ in range(200):
            metrics = measurer.estimate(
                text=text,
                box_width_dots=rect.w,
                font_height_dots=current_h,
                font_width_dots=current_w,
                wrap=wrap,
                line_spacing_dots=line_spacing,
            )
            if metrics.lines <= max_lines and metrics.height_dots <= rect.h and metrics.width_dots <= rect.w:
                return (current_h, current_w)
            current_h = max(1, int(current_h * 0.95))
            current_w = max(1, int(current_w * 0.95))
            if current_h == 1 and current_w == 1:
                return (current_h, current_w)
        return (current_h, current_w)

    def _text_measurer_for_dpi(self, dpi: int) -> TextMeasurer:
        measurer = self.text_measurer
        if hasattr(measurer, 'for_dpi'):
            return measurer.for_dpi(dpi)  # type: ignore[no-any-return]
        return measurer

    def _align_in_rect(self, *, rect, size_w: int, size_h: int, align_h: str, align_v: str) -> tuple[int, int]:
        x = rect.x
        y = rect.y
        if align_h == 'center':
            x = rect.x + max(0, (rect.w - size_w) // 2)
        elif align_h == 'right':
            x = rect.x + max(0, rect.w - size_w)
        if align_v == 'center':
            y = rect.y + max(0, (rect.h - size_h) // 2)
        elif align_v == 'bottom':
            y = rect.y + max(0, rect.h - size_h)
        return x, y

    def _max_qr_magnification(self, *, data: str, ecc: str, inner_size: int, fallback: int) -> int:
        try:
            if not data.isascii():
                raise ValueError('QR data contains non-ASCII')
            sym = QrCodeZplBuilder(
                magnification=1,
                ecc=ecc,  # type: ignore[arg-type]
                model=2,
                orientation='N',
            ).build(data, x=0, y=0)
            size = max(1, max(sym.size_dots.symbol_width, sym.size_dots.symbol_height))
            max_mag = inner_size // size
            return clamp_int(max_mag, 1, 10)
        except Exception:
            return clamp_int(fallback, 1, 10)

    def _emit_qr(self, z: ZplBuilder, *, element: QrElement, rect, variables: Mapping[str, Any], render_opts: RenderOptions, dpi: int) -> None:
        render_mode = element.render_mode or 'zpl'
        if render_mode == 'image':
            self._emit_qr_image(z, element=element, rect=rect, variables=variables, render_opts=render_opts, dpi=dpi)
            return
        if render_mode != 'zpl':
            raise CompilationError(f'unsupported QR render_mode: {render_mode!r}')

        data = render_text(element.data, variables, options=render_opts)
        qz_mm = element.quiet_zone_mm
        if qz_mm is None:
            qz_mm = float(element.extensions.get('quiet_zone_mm', 0.0)) if element.extensions else 0.0
        qz = mm_to_dots(float(qz_mm), dpi) if qz_mm else 0
        inner = rect.inset(left=qz, top=qz, right=qz, bottom=qz)

        model = 2
        mag = element.magnification or _default_qr_magnification(dpi)
        size_mode = element.size_mode or 'fixed'
        align_h = element.align_h or 'center'
        align_v = element.align_v or 'center'
        if size_mode not in ('fixed', 'max'):
            raise CompilationError(f'unsupported QR size_mode: {size_mode!r}')
        if align_h not in ('left', 'center', 'right'):
            raise CompilationError(f'unsupported QR align_h: {align_h!r}')
        if align_v not in ('top', 'center', 'bottom'):
            raise CompilationError(f'unsupported QR align_v: {align_v!r}')

        ecc = str(element.error_correction or 'M')
        input_mode = str(element.input_mode or 'A')
        if input_mode not in ('A', 'M'):
            raise CompilationError(f'unsupported QR input_mode: {input_mode!r}')
        if input_mode == 'M' and not element.character_mode:
            raise CompilationError('QR character_mode is required when input_mode is "M"')

        if size_mode == 'max':
            inner_size = max(1, min(inner.w, inner.h))
            mag = self._max_qr_magnification(data=data, ecc=ecc, inner_size=inner_size, fallback=mag)

        size_w = max(1, min(inner.w, inner.h))
        size_h = size_w
        try:
            if not data.isascii():
                raise ValueError('QR data contains non-ASCII')
            size_data: str | bytes = data
            sym = QrCodeZplBuilder(
                magnification=int(mag),
                ecc=ecc,  # type: ignore[arg-type]
                model=model,
                orientation='N',
            ).build(size_data, x=0, y=0)
            size_w = max(1, sym.size_dots.symbol_width)
            size_h = max(1, sym.size_dots.symbol_height)
        except Exception:
            pass

        x, y = self._align_in_rect(rect=inner, size_w=size_w, size_h=size_h, align_h=align_h, align_v=align_v)
        x = max(0, x)
        y = max(0, y)

        if input_mode == 'A':
            fd = f'{ecc}A,{data}'
        else:
            cm = element.character_mode or 'A'
            fd = f'{ecc}M,{cm}{data}'

        needs_hex, encoded = encode_field_data(fd, hex_indicator='_', encoding='utf-8')
        z.field_origin(x, y)
        z.qr_code(model=model, magnification=int(mag))
        if needs_hex:
            z.field_hex('_')
        z.field_data(encoded)
        z.field_separator()

    def _emit_datamatrix(self, z: ZplBuilder, *, element: DataMatrixElement, rect, variables: Mapping[str, Any], render_opts: RenderOptions, dpi: int) -> None:
        render_mode = element.render_mode or 'zpl'
        if render_mode == 'image':
            self._emit_datamatrix_image(z, element=element, rect=rect, variables=variables, render_opts=render_opts, dpi=dpi)
            return
        if render_mode != 'zpl':
            raise CompilationError(f'unsupported DataMatrix render_mode: {render_mode!r}')

        data = render_text(element.data, variables, options=render_opts)
        qz_mm = element.quiet_zone_mm
        if qz_mm is None:
            qz_mm = float(element.extensions.get('quiet_zone_mm', 0.0)) if element.extensions else 0.0
        qz = mm_to_dots(float(qz_mm), dpi) if qz_mm else 0
        inner = rect.inset(left=qz, top=qz, right=qz, bottom=qz)

        module_mm = element.module_size_mm or 0.5
        size_mode = element.size_mode or 'fixed'
        align_h = element.align_h or 'center'
        align_v = element.align_v or 'center'
        if size_mode not in ('fixed', 'max'):
            raise CompilationError(f'unsupported DataMatrix size_mode: {size_mode!r}')
        if align_h not in ('left', 'center', 'right'):
            raise CompilationError(f'unsupported DataMatrix align_h: {align_h!r}')
        if align_v not in ('top', 'center', 'bottom'):
            raise CompilationError(f'unsupported DataMatrix align_v: {align_v!r}')
        quality = int(element.quality or 200)
        if quality != 200:
            raise CompilationError('DataMatrix quality must be 200 (ECC200)')
        columns = int(element.columns or 0)
        rows = int(element.rows or 0)
        format_id = int(element.format_id or 6)
        escape_char = element.escape_char or '_'
        if len(escape_char) != 1:
            raise CompilationError('DataMatrix escape_char must be a single character')

        if size_mode == 'max':
            if columns <= 0 or rows <= 0:
                raise CompilationError('DataMatrix size_mode "max" requires explicit columns and rows')
            module = max(1, min(inner.w // columns, inner.h // rows))
        else:
            module = max(1, mm_to_dots(float(module_mm), dpi))

        size_w = max(1, min(inner.w, inner.h))
        size_h = size_w
        if columns > 0 and rows > 0:
            try:
                sym = DataMatrixZplBuilder(
                    module_size=module,
                    columns=columns,
                    rows=rows,
                    quality=quality,
                    escape_char=escape_char,
                ).build(data, x=0, y=0)
                size_w = max(1, sym.size_dots.symbol_width)
                size_h = max(1, sym.size_dots.symbol_height)
            except Exception:
                pass

        x, y = self._align_in_rect(rect=inner, size_w=size_w, size_h=size_h, align_h=align_h, align_v=align_v)

        needs_hex, encoded = encode_field_data(data, hex_indicator=escape_char, encoding='utf-8')
        z.field_origin(x, y)
        z.datamatrix(
            module_size=module,
            quality=quality,
            columns=columns,
            rows=rows,
            format_id=format_id,
            escape_char=escape_char,
        )
        if needs_hex:
            z.field_hex(escape_char)
        z.field_data(encoded)
        z.field_separator()

    def _emit_line(self, z: ZplBuilder, *, element: LineElement, rect, dpi: int) -> None:
        thickness = max(1, mm_to_dots(float(element.thickness_mm), dpi))
        align = element.align or 'center'
        if element.orientation == 'h':
            y = rect.y
            if align == 'center':
                y = rect.y + max(0, (rect.h - thickness) // 2)
            elif align == 'end':
                y = rect.y + max(0, rect.h - thickness)
            z.field_origin(rect.x, y)
            z.graphic_box(width=max(1, rect.w), height=thickness, thickness=thickness, color='B', rounding=0)
            z.field_separator()
        else:
            x = rect.x
            if align == 'center':
                x = rect.x + max(0, (rect.w - thickness) // 2)
            elif align == 'end':
                x = rect.x + max(0, rect.w - thickness)
            z.field_origin(x, rect.y)
            z.graphic_box(width=thickness, height=max(1, rect.h), thickness=thickness, color='B', rounding=0)
            z.field_separator()

    def _emit_qr_image(
        self,
        z: ZplBuilder,
        *,
        element: QrElement,
        rect,
        variables: Mapping[str, Any],
        render_opts: RenderOptions,
        dpi: int,
    ) -> None:
        data = render_text(element.data, variables, options=render_opts)
        qz_mm = element.quiet_zone_mm
        if qz_mm is None:
            qz_mm = float(element.extensions.get('quiet_zone_mm', 0.0)) if element.extensions else 0.0
        qz = mm_to_dots(float(qz_mm), dpi) if qz_mm else 0
        inner = rect.inset(left=qz, top=qz, right=qz, bottom=qz)

        size_mode = element.size_mode or 'fixed'
        align_h = element.align_h or 'center'
        align_v = element.align_v or 'center'
        if size_mode not in ('fixed', 'max'):
            raise CompilationError(f'unsupported QR size_mode: {size_mode!r}')
        if align_h not in ('left', 'center', 'right'):
            raise CompilationError(f'unsupported QR align_h: {align_h!r}')
        if align_v not in ('top', 'center', 'bottom'):
            raise CompilationError(f'unsupported QR align_v: {align_v!r}')

        ecc = str(element.error_correction or 'M')
        input_mode = str(element.input_mode or 'A')
        if input_mode not in ('A', 'M'):
            raise CompilationError(f'unsupported QR input_mode: {input_mode!r}')
        if input_mode == 'M' and not element.character_mode:
            raise CompilationError('QR character_mode is required when input_mode is "M"')

        qr = _qr_make_symbol(data=data, ecc=ecc, input_mode=input_mode, character_mode=element.character_mode)
        matrix = list(qr.matrix)
        modules = len(matrix)
        if modules <= 0:
            raise CompilationError('QR matrix is empty')

        mag = element.magnification or _default_qr_magnification(dpi)
        if size_mode == 'max':
            inner_size = max(1, min(inner.w, inner.h))
            mag = max(1, inner_size // modules)

        size_w = max(1, modules * int(mag))
        size_h = size_w

        theme = element.theme or {}
        preset = theme.get('preset')
        if preset == 'dots':
            module_shape = 'circle'
            finder_shape = 'square'
        elif preset == 'rounded':
            module_shape = 'rounded'
            finder_shape = 'rounded'
        else:
            module_shape = 'square'
            finder_shape = 'square'

        module_shape = theme.get('module_shape') or module_shape
        finder_shape = theme.get('finder_shape') or finder_shape
        if module_shape not in ('square', 'circle', 'rounded'):
            raise CompilationError(f'unsupported QR module_shape: {module_shape!r}')
        if finder_shape not in ('square', 'circle', 'rounded'):
            raise CompilationError(f'unsupported QR finder_shape: {finder_shape!r}')

        x, y = self._align_in_rect(rect=inner, size_w=size_w, size_h=size_h, align_h=align_h, align_v=align_v)

        try:
            from PIL import Image, ImageDraw
        except Exception as e:
            raise CompilationError(f'Pillow is required for QR images: {e}') from e

        img = Image.new('L', (size_w, size_h), 255)
        draw = ImageDraw.Draw(img)
        for row_idx, row in enumerate(matrix):
            for col_idx, is_dark in enumerate(row):
                if not is_dark:
                    continue
                shape = finder_shape if _qr_is_finder_module(row_idx, col_idx, modules) else module_shape
                x0 = col_idx * int(mag)
                y0 = row_idx * int(mag)
                x1 = x0 + int(mag)
                y1 = y0 + int(mag)
                if shape == 'circle':
                    draw.ellipse((x0, y0, x1 - 1, y1 - 1), fill=0)
                elif shape == 'rounded':
                    radius = max(1, int(mag) // 3)
                    if hasattr(draw, 'rounded_rectangle') and int(mag) >= 3:
                        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius, fill=0)
                    else:
                        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)
                else:
                    draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=0)

        data_hex, bytes_per_row, total_bytes = self._image_to_gfa(
            img,
            invert=False,
            threshold=128,
            dither='none',
        )
        z.field_origin(x, y)
        z.graphic_field(total_bytes=total_bytes, bytes_per_row=bytes_per_row, data=data_hex)
        z.field_separator()

    def _emit_datamatrix_image(
        self,
        z: ZplBuilder,
        *,
        element: DataMatrixElement,
        rect,
        variables: Mapping[str, Any],
        render_opts: RenderOptions,
        dpi: int,
    ) -> None:
        data = render_text(element.data, variables, options=render_opts)
        qz_mm = element.quiet_zone_mm
        if qz_mm is None:
            qz_mm = float(element.extensions.get('quiet_zone_mm', 0.0)) if element.extensions else 0.0
        qz = mm_to_dots(float(qz_mm), dpi) if qz_mm else 0
        inner = rect.inset(left=qz, top=qz, right=qz, bottom=qz)

        size_mode = element.size_mode or 'fixed'
        align_h = element.align_h or 'center'
        align_v = element.align_v or 'center'
        if size_mode not in ('fixed', 'max'):
            raise CompilationError(f'unsupported DataMatrix size_mode: {size_mode!r}')
        if align_h not in ('left', 'center', 'right'):
            raise CompilationError(f'unsupported DataMatrix align_h: {align_h!r}')
        if align_v not in ('top', 'center', 'bottom'):
            raise CompilationError(f'unsupported DataMatrix align_v: {align_v!r}')

        img = _datamatrix_image_from_data(data)
        w, h = img.size
        if w <= 0 or h <= 0:
            raise CompilationError('DataMatrix image is empty')

        try:
            from PIL import Image
            resample = Image.Resampling.NEAREST
        except Exception:
            resample = 0

        if size_mode == 'max':
            scale = min(inner.w / w, inner.h / h) if w and h else 1.0
            target_w = max(1, int(round(w * scale)))
            target_h = max(1, int(round(h * scale)))
        else:
            module_mm = element.module_size_mm or 0.5
            module = max(1, mm_to_dots(float(module_mm), dpi))
            target_w = max(1, w * module)
            target_h = max(1, h * module)

        if target_w != w or target_h != h:
            img = img.resize((target_w, target_h), resample=resample)

        x, y = self._align_in_rect(rect=inner, size_w=target_w, size_h=target_h, align_h=align_h, align_v=align_v)

        data_hex, bytes_per_row, total_bytes = self._image_to_gfa(
            img,
            invert=False,
            threshold=128,
            dither='none',
        )
        z.field_origin(x, y)
        z.graphic_field(total_bytes=total_bytes, bytes_per_row=bytes_per_row, data=data_hex)
        z.field_separator()

    def _emit_image(
        self,
        z: ZplBuilder,
        *,
        element: ImageElement,
        rect,
        variables: Mapping[str, Any],
        render_opts: RenderOptions,
        dpi: int,
    ) -> None:
        if rect.w <= 0 or rect.h <= 0:
            return

        source_kind = element.source.kind
        source_data = render_text(element.source.data, variables, options=render_opts)
        image_bytes = self._load_image_bytes(kind=source_kind, data=source_data)
        if not image_bytes:
            raise CompilationError('image source data is empty')

        img = self._decode_image(image_bytes)
        fit = element.fit or 'contain'
        align_h = element.align_h or 'center'
        align_v = element.align_v or 'center'
        input_dpi = int(element.input_dpi) if element.input_dpi else None
        threshold = int(element.threshold) if element.threshold is not None else 128
        dither = element.dither or 'none'
        invert = bool(element.invert) if element.invert is not None else False

        if fit not in ('none', 'contain', 'cover', 'stretch'):
            raise CompilationError(f'unsupported image fit: {fit!r}')
        if align_h not in ('left', 'center', 'right'):
            raise CompilationError(f'unsupported image align_h: {align_h!r}')
        if align_v not in ('top', 'center', 'bottom'):
            raise CompilationError(f'unsupported image align_v: {align_v!r}')
        if dither not in ('none', 'floyd_steinberg', 'bayer'):
            raise CompilationError(f'unsupported image dither: {dither!r}')
        if threshold < 0 or threshold > 255:
            raise CompilationError('image threshold must be between 0 and 255')

        target_img, size_w, size_h = self._prepare_image(
            img,
            rect_w=rect.w,
            rect_h=rect.h,
            fit=fit,
            input_dpi=input_dpi,
            target_dpi=dpi,
        )
        if size_w <= 0 or size_h <= 0:
            return

        if fit == 'cover':
            x = rect.x
            y = rect.y
        else:
            x, y = self._align_in_rect(rect=rect, size_w=size_w, size_h=size_h, align_h=align_h, align_v=align_v)

        data, bytes_per_row, total_bytes = self._image_to_gfa(
            target_img,
            invert=invert,
            threshold=threshold,
            dither=dither,
        )
        z.field_origin(x, y)
        z.graphic_field(total_bytes=total_bytes, bytes_per_row=bytes_per_row, data=data)
        z.field_separator()

    def _load_image_bytes(self, *, kind: str, data: str) -> bytes:
        if kind == 'base64':
            payload = data.strip()
            if payload.startswith('data:'):
                _, _, payload = payload.partition(',')
            try:
                return base64.b64decode(payload, validate=True)
            except Exception as e:
                raise CompilationError(f'failed to decode base64 image data: {e}') from e

        if kind == 'url':
            if not _env_flag_enabled('ZPLGRID_ENABLE_IMAGE_URL'):
                raise CompilationError('image url fetching is disabled (set ZPLGRID_ENABLE_IMAGE_URL=1 to enable)')
            url = data.strip()
            if not url.lower().startswith(('http://', 'https://')):
                raise CompilationError('image url must start with http:// or https://')
            timeout_s = _env_float('ZPLGRID_IMAGE_URL_TIMEOUT_S', default=5.0)
            max_bytes = _env_int('ZPLGRID_IMAGE_MAX_BYTES', default=5_000_000)
            try:
                import requests
                resp = requests.get(url, timeout=timeout_s)
                resp.raise_for_status()
                content = resp.content
            except Exception as e:
                raise CompilationError(f'failed to fetch image url: {e}') from e
            if max_bytes > 0 and len(content) > max_bytes:
                raise CompilationError(f'image exceeds max size ({len(content)} bytes > {max_bytes} bytes)')
            return content

        raise CompilationError(f'unsupported image source kind: {kind!r}')

    def _decode_image(self, data: bytes):
        try:
            from PIL import Image
        except Exception as e:
            raise CompilationError(f'Pillow is required for images: {e}') from e
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as e:
            raise CompilationError(f'failed to decode image: {e}') from e

        if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
            bg = Image.new('RGBA', img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(bg, img.convert('RGBA')).convert('RGB')
        else:
            img = img.convert('RGB')
        return img

    def _prepare_image(
        self,
        img,
        *,
        rect_w: int,
        rect_h: int,
        fit: str,
        input_dpi: Optional[int],
        target_dpi: int,
    ):
        if rect_w <= 0 or rect_h <= 0:
            return img, 0, 0
        w, h = img.size
        if w <= 0 or h <= 0:
            return img, 0, 0

        try:
            from PIL import Image
            resample = Image.Resampling.LANCZOS
        except Exception:
            resample = 1

        if fit == 'none':
            if input_dpi:
                scale = float(target_dpi) / float(input_dpi)
                w = max(1, int(round(w * scale)))
                h = max(1, int(round(h * scale)))
                if w != img.size[0] or h != img.size[1]:
                    img = img.resize((w, h), resample=resample)
            return img, w, h

        if fit == 'stretch':
            if w != rect_w or h != rect_h:
                img = img.resize((rect_w, rect_h), resample=resample)
            return img, rect_w, rect_h

        if fit in ('contain', 'cover'):
            scale = min(rect_w / w, rect_h / h) if fit == 'contain' else max(rect_w / w, rect_h / h)
            target_w = max(1, int(round(w * scale)))
            target_h = max(1, int(round(h * scale)))
            if target_w != w or target_h != h:
                img = img.resize((target_w, target_h), resample=resample)
            if fit == 'cover':
                left = max(0, (target_w - rect_w) // 2)
                top = max(0, (target_h - rect_h) // 2)
                right = left + rect_w
                bottom = top + rect_h
                img = img.crop((left, top, right, bottom))
                return img, rect_w, rect_h
            return img, target_w, target_h

        return img, w, h

    def _image_to_gfa(self, img, *, invert: bool, threshold: int, dither: str) -> tuple[str, int, int]:
        from PIL import Image

        if dither == 'floyd_steinberg':
            bw = img.convert('L').convert('1', dither=Image.FLOYDSTEINBERG)
            pixels = bw.load()
            w, h = bw.size
            get_pixel = lambda x, y: pixels[x, y]
            to_black = lambda v: v == 0
        else:
            gray = img.convert('L')
            pixels = gray.load()
            w, h = gray.size
            if dither == 'bayer':
                matrix = (
                    (0, 8, 2, 10),
                    (12, 4, 14, 6),
                    (3, 11, 1, 9),
                    (15, 7, 13, 5),
                )
                offset = threshold - 128

                def to_black(value, x, y):
                    t = (matrix[y % 4][x % 4] + 0.5) * 16
                    return (value + offset) < t
            else:
                def to_black(value, _x, _y):
                    return value < threshold

            get_pixel = lambda x, y: pixels[x, y]

        bytes_per_row = (w + 7) // 8
        data_bytes = bytearray()
        for y in range(h):
            byte = 0
            bit = 7
            for x in range(w):
                if dither == 'floyd_steinberg':
                    is_black = to_black(get_pixel(x, y))
                else:
                    is_black = to_black(get_pixel(x, y), x, y)
                if invert:
                    is_black = not is_black
                if is_black:
                    byte |= (1 << bit)
                bit -= 1
                if bit < 0:
                    data_bytes.append(byte)
                    byte = 0
                    bit = 7
            if bit != 7:
                data_bytes.append(byte)

        total_bytes = len(data_bytes)
        hex_data = ''.join(f'{b:02X}' for b in data_bytes)
        return hex_data, bytes_per_row, total_bytes


def _env_flag_enabled(name: str) -> bool:
    value = os.getenv(name, '')
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def _env_float(name: str, *, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, *, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _qr_make_symbol(*, data: str, ecc: str, input_mode: str, character_mode: Optional[str]):
    try:
        import segno
    except Exception as e:
        raise CompilationError(f'QR image rendering requires segno: {e}') from e

    mode = None
    if input_mode == 'M':
        if character_mode == 'N':
            mode = 'numeric'
        elif character_mode == 'A':
            mode = 'alphanumeric'
        else:
            mode = 'byte'

    payload: str | bytes
    if data.isascii():
        payload = data
    else:
        payload = data.encode('utf-8')

    try:
        return segno.make(payload, error=ecc, mode=mode, micro=False)
    except Exception as e:
        raise CompilationError(f'failed to build QR image: {e}') from e


def _datamatrix_image_from_data(data: str):
    try:
        from PIL import Image
    except Exception as e:
        raise CompilationError(f'Pillow is required for DataMatrix images: {e}') from e
    try:
        from pylibdmtx import pylibdmtx
    except Exception as e:
        raise CompilationError(f'DataMatrix image rendering requires pylibdmtx: {e}') from e

    payload = data.encode('utf-8')
    try:
        encoded = pylibdmtx.encode(payload)
        img = Image.frombytes('RGB', (encoded.width, encoded.height), encoded.pixels)
        return img.convert('L')
    except Exception as e:
        raise CompilationError(f'failed to build DataMatrix image: {e}') from e


def _qr_is_finder_module(row: int, col: int, modules: int) -> bool:
    if modules < 21:
        return False
    if row < 7 and col < 7:
        return True
    if row < 7 and col >= modules - 7:
        return True
    if row >= modules - 7 and col < 7:
        return True
    return False




def _default_qr_magnification(dpi: int) -> int:
    if dpi <= 160:
        return 1
    if dpi <= 250:
        return 2
    if dpi <= 350:
        return 3
    return 4
