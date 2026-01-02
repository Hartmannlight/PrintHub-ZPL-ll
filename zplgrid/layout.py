from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .exceptions import LayoutError
from .model import LeafNode, Node, Rect, SplitNode
from .units import mm_to_dots


@dataclass(frozen=True)
class SplitDividerLayout:
    rect: Rect
    thickness: int


@dataclass(frozen=True)
class GutterGuideLayout:
    rect: Rect
    direction: str


@dataclass(frozen=True)
class LeafLayout:
    node_id: str
    node: LeafNode
    rect: Rect
    content_rect: Rect


@dataclass(frozen=True)
class LayoutResult:
    node_rects: Mapping[str, Rect]
    leaves: tuple[LeafLayout, ...]
    dividers: tuple[SplitDividerLayout, ...]
    gutters: tuple[GutterGuideLayout, ...]
    alias_to_id: Mapping[str, str]


def compute_layout(root: Node, *, width_dots: int, height_dots: int, dpi: int) -> LayoutResult:
    node_rects: dict[str, Rect] = {}
    leaves: list[LeafLayout] = []
    dividers: list[SplitDividerLayout] = []
    gutters: list[GutterGuideLayout] = []
    alias_to_id: dict[str, str] = {}

    root_rect = Rect(x=0, y=0, w=width_dots, h=height_dots)
    _walk(
        root,
        node_id='r',
        rect=root_rect,
        dpi=dpi,
        node_rects=node_rects,
        leaves=leaves,
        dividers=dividers,
        gutters=gutters,
        alias_to_id=alias_to_id,
    )
    return LayoutResult(
        node_rects=node_rects,
        leaves=tuple(leaves),
        dividers=tuple(dividers),
        gutters=tuple(gutters),
        alias_to_id=alias_to_id,
    )


def _walk(
    node: Node,
    *,
    node_id: str,
    rect: Rect,
    dpi: int,
    node_rects: dict[str, Rect],
    leaves: list[LeafLayout],
    dividers: list[SplitDividerLayout],
    gutters: list[GutterGuideLayout],
    alias_to_id: dict[str, str],
) -> None:
    node_rects[node_id] = rect
    if node.alias:
        alias_to_id[node.alias] = node_id

    if isinstance(node, LeafNode):
        pad = node.padding_mm
        left = mm_to_dots(pad.left, dpi)
        top = mm_to_dots(pad.top, dpi)
        right = mm_to_dots(pad.right, dpi)
        bottom = mm_to_dots(pad.bottom, dpi)
        content = rect.inset(left=left, top=top, right=right, bottom=bottom)
        leaves.append(LeafLayout(node_id=node_id, node=node, rect=rect, content_rect=content))
        return

    if not isinstance(node, SplitNode):
        raise LayoutError(f'unknown node type at {node_id}')

    if rect.w < 0 or rect.h < 0:
        raise LayoutError(f'negative rect at {node_id}')

    gutter = mm_to_dots(node.gutter_mm, dpi)
    if node.direction == 'v':
        available = rect.w - gutter
        if available < 0:
            raise LayoutError(f'gutter too large at {node_id}')
        child0_w = int(available * node.ratio)
        child0_w = max(0, min(child0_w, available))
        child1_w = available - child0_w
        child0 = Rect(x=rect.x, y=rect.y, w=child0_w, h=rect.h)
        child1 = Rect(x=rect.x + child0_w + gutter, y=rect.y, w=child1_w, h=rect.h)
        if gutter > 0:
            gutters.append(GutterGuideLayout(rect=Rect(x=rect.x + child0_w, y=rect.y, w=gutter, h=rect.h), direction='v'))
        if node.divider.visible:
            thickness = mm_to_dots(node.divider.thickness_mm, dpi)
            line_x = rect.x + child0_w + (gutter - thickness) // 2
            dividers.append(SplitDividerLayout(rect=Rect(x=line_x, y=rect.y, w=thickness, h=rect.h), thickness=thickness))
        _walk(node.children[0], node_id=f'{node_id}/0', rect=child0, dpi=dpi, node_rects=node_rects, leaves=leaves, dividers=dividers, gutters=gutters, alias_to_id=alias_to_id)
        _walk(node.children[1], node_id=f'{node_id}/1', rect=child1, dpi=dpi, node_rects=node_rects, leaves=leaves, dividers=dividers, gutters=gutters, alias_to_id=alias_to_id)
        return

    if node.direction == 'h':
        available = rect.h - gutter
        if available < 0:
            raise LayoutError(f'gutter too large at {node_id}')
        child0_h = int(available * node.ratio)
        child0_h = max(0, min(child0_h, available))
        child1_h = available - child0_h
        child0 = Rect(x=rect.x, y=rect.y, w=rect.w, h=child0_h)
        child1 = Rect(x=rect.x, y=rect.y + child0_h + gutter, w=rect.w, h=child1_h)
        if gutter > 0:
            gutters.append(GutterGuideLayout(rect=Rect(x=rect.x, y=rect.y + child0_h, w=rect.w, h=gutter), direction='h'))
        if node.divider.visible:
            thickness = mm_to_dots(node.divider.thickness_mm, dpi)
            line_y = rect.y + child0_h + (gutter - thickness) // 2
            dividers.append(SplitDividerLayout(rect=Rect(x=rect.x, y=line_y, w=rect.w, h=thickness), thickness=thickness))
        _walk(node.children[0], node_id=f'{node_id}/0', rect=child0, dpi=dpi, node_rects=node_rects, leaves=leaves, dividers=dividers, gutters=gutters, alias_to_id=alias_to_id)
        _walk(node.children[1], node_id=f'{node_id}/1', rect=child1, dpi=dpi, node_rects=node_rects, leaves=leaves, dividers=dividers, gutters=gutters, alias_to_id=alias_to_id)
        return

    raise LayoutError(f'invalid split direction at {node_id}: {node.direction!r}')
