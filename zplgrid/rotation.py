from __future__ import annotations

from dataclasses import dataclass

from .model import Rect


@dataclass(frozen=True)
class Transform:
    """Quarter-turn transform from a node's local coordinates to label dots."""

    a: int = 1
    b: int = 0
    c: int = 0
    d: int = 1
    x: int = 0
    y: int = 0

    def point(self, x: int, y: int) -> tuple[int, int]:
        return self.a * x + self.c * y + self.x, self.b * x + self.d * y + self.y

    def bounds(self, rect: Rect) -> Rect:
        points = [self.point(x, y) for x in (rect.x, rect.x + rect.w) for y in (rect.y, rect.y + rect.h)]
        xs, ys = zip(*points)
        return Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    def child(self, rect: Rect, rotation: int) -> tuple[Transform, Rect]:
        turns = (rotation % 360) // 90
        a, b, c, d, x, y = (
            (1, 0, 0, 1, rect.x, rect.y),
            (0, 1, -1, 0, rect.x + rect.w, rect.y),
            (-1, 0, 0, -1, rect.x + rect.w, rect.y + rect.h),
            (0, -1, 1, 0, rect.x, rect.y + rect.h),
        )[turns]
        tx, ty = self.point(x, y)
        transform = Transform(
            self.a * a + self.c * b, self.b * a + self.d * b,
            self.a * c + self.c * d, self.b * c + self.d * d, tx, ty,
        )
        local = Rect(0, 0, rect.h if turns % 2 else rect.w, rect.w if turns % 2 else rect.h)
        return transform, local

    @property
    def orientation(self) -> str:
        return {(1, 0): 'N', (0, 1): 'R', (-1, 0): 'I', (0, -1): 'B'}[(self.a, self.b)]


class TransformedZplBuilder:
    """Map field bounding boxes and bitmap pixels; keep typography in local axes."""

    def __init__(self, builder, transform: Transform):
        self.builder = builder
        self.transform = transform
        self.origin = (0, 0)
        self.size = (0, 0)

    def __getattr__(self, name):
        return getattr(self.builder, name)

    def field_origin(self, x: int, y: int, *, width: int = 0, height: int = 0) -> None:
        self.origin = x, y
        self.size = width, height

    def _emit_origin(self, width: int, height: int) -> Rect:
        rect = self.transform.bounds(Rect(*self.origin, width, height))
        self.builder.field_origin(rect.x, rect.y)
        return rect

    def font_a0(self, *, height: int, width: int, box_width: int = 0) -> None:
        self._emit_origin(box_width, height)
        self.builder.font_a0(height=height, width=width, orientation=self.transform.orientation)

    def qr_code(self, *, model: int, magnification: int) -> None:
        self._emit_origin(*self.size)
        self.builder.qr_code(model=model, magnification=magnification, orientation=self.transform.orientation)

    def datamatrix(self, **kwargs) -> None:
        self._emit_origin(*self.size)
        self.builder.datamatrix(**kwargs, orientation=self.transform.orientation)

    def graphic_box(self, *, width: int, height: int, **kwargs) -> None:
        rect = self._emit_origin(width, height)
        self.builder.graphic_box(width=rect.w, height=rect.h, **kwargs)

    def graphic_field(self, *, total_bytes: int, bytes_per_row: int, data: str, width: int | None = None) -> None:
        from PIL import Image

        pixel_width = width or bytes_per_row * 8
        height = total_bytes // bytes_per_row
        rect = self._emit_origin(pixel_width, height)
        if self.transform.orientation != 'N':
            # ZPL stores black as 1. Preserve that convention while transposing.
            image = Image.frombytes('1', (bytes_per_row * 8, height), bytes.fromhex(data))
            image = image.crop((0, 0, pixel_width, height))
            transpose = {'R': Image.Transpose.ROTATE_270, 'I': Image.Transpose.ROTATE_180, 'B': Image.Transpose.ROTATE_90}
            image = image.transpose(transpose[self.transform.orientation])
            bytes_per_row = (rect.w + 7) // 8
            raw = image.tobytes()
            total_bytes, data = len(raw), raw.hex().upper()
        self.builder.graphic_field(total_bytes=total_bytes, bytes_per_row=bytes_per_row, data=data)
