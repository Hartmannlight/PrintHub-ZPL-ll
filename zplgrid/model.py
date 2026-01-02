from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class PaddingMm:
    top: float
    right: float
    bottom: float
    left: float

    @classmethod
    def from_list(cls, values: Sequence[float]) -> 'PaddingMm':
        if len(values) != 4:
            raise ValueError('padding must have 4 numbers: [top, right, bottom, left]')
        top, right, bottom, left = (float(v) for v in values)
        if min(top, right, bottom, left) < 0:
            raise ValueError('padding values must be >= 0')
        return cls(top=top, right=right, bottom=bottom, left=left)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.top, self.right, self.bottom, self.left)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def inset(self, left: int, top: int, right: int, bottom: int) -> 'Rect':
        x = self.x + left
        y = self.y + top
        w = max(0, self.w - left - right)
        h = max(0, self.h - top - bottom)
        return Rect(x=x, y=y, w=w, h=h)


@dataclass(frozen=True)
class LabelTarget:
    width_mm: float
    height_mm: float
    dpi: int = 203
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0


@dataclass(frozen=True)
class Divider:
    visible: bool = False
    thickness_mm: float = 0.3


@dataclass(frozen=True)
class TemplateDefaults:
    leaf_padding_mm: PaddingMm = field(default_factory=lambda: PaddingMm(1.0, 1.0, 1.0, 1.0))
    text_defaults: dict[str, Any] = field(default_factory=dict)
    code2d_defaults: dict[str, Any] = field(default_factory=dict)
    image_defaults: dict[str, Any] = field(default_factory=dict)
    render_defaults: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Element:
    type: str
    id: Optional[str] = None
    padding_mm: PaddingMm = field(default_factory=lambda: PaddingMm(0.0, 0.0, 0.0, 0.0))
    min_size_mm: Optional[tuple[float, float]] = None
    max_size_mm: Optional[tuple[float, float]] = None
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextElement(Element):
    text: str = ''
    font_height_mm: Optional[float] = None
    font_width_mm: Optional[float] = None
    wrap: Optional[str] = None
    fit: Optional[str] = None
    max_lines: Optional[int] = None
    align_h: Optional[str] = None
    align_v: Optional[str] = None


@dataclass(frozen=True)
class QrElement(Element):
    data: str = ''
    magnification: Optional[int] = None
    size_mode: Optional[str] = None
    align_h: Optional[str] = None
    align_v: Optional[str] = None
    error_correction: str = 'M'
    input_mode: str = 'A'
    character_mode: Optional[str] = None
    quiet_zone_mm: Optional[float] = None
    render_mode: Optional[str] = None
    theme: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataMatrixElement(Element):
    data: str = ''
    module_size_mm: Optional[float] = None
    size_mode: Optional[str] = None
    align_h: Optional[str] = None
    align_v: Optional[str] = None
    quality: int = 200
    columns: int = 0
    rows: int = 0
    format_id: int = 6
    escape_char: str = '_'
    quiet_zone_mm: Optional[float] = None
    render_mode: Optional[str] = None


@dataclass(frozen=True)
class LineElement(Element):
    orientation: str = 'h'
    thickness_mm: float = 0.3
    align: str = 'center'


@dataclass(frozen=True)
class ImageSource:
    kind: str
    data: str


@dataclass(frozen=True)
class ImageElement(Element):
    source: ImageSource = field(default_factory=lambda: ImageSource(kind='base64', data=''))
    fit: Optional[str] = None
    align_h: Optional[str] = None
    align_v: Optional[str] = None
    input_dpi: Optional[int] = None
    threshold: Optional[int] = None
    dither: Optional[str] = None
    invert: Optional[bool] = None


@dataclass(frozen=True)
class Node:
    kind: str
    alias: Optional[str] = None
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SplitNode(Node):
    direction: str = 'v'
    ratio: float = 0.5
    gutter_mm: float = 0.0
    divider: Divider = field(default_factory=Divider)
    children: tuple['Node', 'Node'] = field(default_factory=tuple)


@dataclass(frozen=True)
class LeafNode(Node):
    padding_mm: Optional[PaddingMm] = None
    debug_border: bool = False
    elements: tuple[Element, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Template:
    schema_version: int
    name: str
    defaults: TemplateDefaults
    layout: Node
    extensions: dict[str, Any] = field(default_factory=dict)

    def compile(self, target: LabelTarget, variables: Optional[Mapping[str, Any]] = None, *, debug: bool = False) -> str:
        from .compiler import Compiler
        return Compiler().compile(self, target=target, variables=dict(variables or {}), debug=debug)
