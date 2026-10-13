from __future__ import annotations

from dataclasses import replace
import math
from numbers import Real

from .exceptions import CompilationError
from .model import LabelTarget, LeafNode, Node, PaddingMm, SplitNode, Template


def prepare_cable_flag(template: Template, target: LabelTarget) -> Node:
    config = template.extensions.get('cable_flag')
    if config is None:
        return template.layout
    if not isinstance(config, dict):
        raise CompilationError('cable_flag must be an object')
    diameter = config.get('diameter_mm', 6)
    padding = config.get('text_padding_mm', 2)
    if any(isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) for value in (diameter, padding)):
        raise CompilationError('Cable diameter and text padding must be finite numbers')
    if diameter <= 0 or padding < 0:
        raise CompilationError('Cable diameter must be positive and text padding nonnegative')
    axis = config.get('wrap_axis', 'long')
    if axis not in ('short', 'long'):
        raise CompilationError('Cable wrap_axis must be short or long')
    horizontal = (target.width_mm <= target.height_mm) if axis == 'short' else (target.width_mm > target.height_mm)
    length = target.width_mm if horizontal else target.height_mm
    circumference = math.pi * diameter
    if (length - circumference) / 2 - padding - 1.5 < 6:
        raise CompilationError('Cable circumference and text padding leave less than 6 mm for text on each flag face')
    root = template.layout
    if not isinstance(root, SplitNode) or root.rotation_deg % 360:
        raise CompilationError('Cable flag requires an unrotated root split; rotate its face areas instead')

    def pad_boundary(node: Node, edge: int | None) -> Node:
        local_edge = None if edge is None else (edge - node.rotation_deg // 90) % 4
        if isinstance(node, LeafNode):
            values = [1.5, 1.5, 1.5, 1.5]
            if local_edge is not None:
                values[local_edge] = padding
            return replace(node, padding_mm=PaddingMm.from_list(values))
        children = []
        for index, child in enumerate(node.children):
            touches = not ((node.direction == 'v' and local_edge in (1, 3) and index != (1 if local_edge == 1 else 0))
                           or (node.direction == 'h' and local_edge in (0, 2) and index != (1 if local_edge == 2 else 0)))
            children.append(pad_boundary(child, local_edge if touches else None))
        return replace(node, children=tuple(children))

    return replace(root, direction='v' if horizontal else 'h', ratio=0.5,
                   gutter_mm=circumference, children=(pad_boundary(root.children[0], 1 if horizontal else 2),
                                                     pad_boundary(root.children[1], 3 if horizontal else 0)))
