from __future__ import annotations

import json
from dataclasses import replace
from typing import Any, Mapping, Optional

from .exceptions import TemplateIssue, TemplateValidationError
from .model import (
    DataMatrixElement,
    Divider,
    ImageElement,
    ImageSource,
    LeafNode,
    LineElement,
    Node,
    PaddingMm,
    QrElement,
    SplitNode,
    Template,
    TemplateDefaults,
    TextElement,
)
from .validation import validate_template_dict


def load_template(data: str | bytes | Mapping[str, Any]) -> Template:
    if isinstance(data, (str, bytes)):
        raw = json.loads(data)
    else:
        raw = dict(data)
    issues = validate_template_dict(raw)
    if issues:
        raise TemplateValidationError(issues)
    return _parse_template_dict(raw)


def _parse_template_dict(raw: Mapping[str, Any]) -> Template:
    schema_version = int(raw['schema_version'])
    name = str(raw.get('name') or 'template')
    defaults = _parse_defaults(raw.get('defaults') or {})
    layout = _parse_node(raw['layout'], defaults=defaults, path='r')
    extensions = dict(raw.get('extensions') or {})
    return Template(schema_version=schema_version, name=name, defaults=defaults, layout=layout, extensions=extensions)


def _parse_defaults(raw: Mapping[str, Any]) -> TemplateDefaults:
    leaf_padding = raw.get('leaf_padding_mm')
    leaf_padding_mm = PaddingMm.from_list(leaf_padding) if leaf_padding is not None else TemplateDefaults().leaf_padding_mm

    text_defaults = dict(raw.get('text') or {})
    code2d_defaults = dict(raw.get('code2d') or {})
    image_defaults = dict(raw.get('image') or {})
    render_defaults = dict(raw.get('render') or {})
    return TemplateDefaults(
        leaf_padding_mm=leaf_padding_mm,
        text_defaults=text_defaults,
        code2d_defaults=code2d_defaults,
        image_defaults=image_defaults,
        render_defaults=render_defaults,
    )


def _parse_node(raw: Mapping[str, Any], *, defaults: TemplateDefaults, path: str) -> Node:
    kind = str(raw['kind'])
    alias = raw.get('alias')
    extensions = dict(raw.get('extensions') or {})

    if kind == 'split':
        divider_raw = raw.get('divider') or {}
        divider = Divider(
            visible=bool(divider_raw.get('visible', False)),
            thickness_mm=float(divider_raw.get('thickness_mm', 0.3)),
        )
        children_raw = raw['children']
        child0 = _parse_node(children_raw[0], defaults=defaults, path=f'{path}/0')
        child1 = _parse_node(children_raw[1], defaults=defaults, path=f'{path}/1')
        return SplitNode(
            kind='split',
            alias=str(alias) if alias is not None else None,
            direction=str(raw['direction']),
            ratio=float(raw['ratio']),
            gutter_mm=float(raw.get('gutter_mm', 0.0)),
            divider=divider,
            children=(child0, child1),
            extensions=extensions,
        )

    if kind == 'leaf':
        padding_raw = raw.get('padding_mm')
        padding_mm = PaddingMm.from_list(padding_raw) if padding_raw is not None else defaults.leaf_padding_mm
        elements_raw = raw.get('elements') or []
        elements = tuple(_parse_element(e, defaults=defaults) for e in elements_raw)
        return LeafNode(
            kind='leaf',
            alias=str(alias) if alias is not None else None,
            padding_mm=padding_mm,
            debug_border=bool(raw.get('debug_border', False)),
            elements=elements,
            extensions=extensions,
        )

    raise ValueError(f'unsupported node kind: {kind}')


def _parse_padding_optional(raw: Optional[list[Any]]) -> PaddingMm:
    if raw is None:
        return PaddingMm(0.0, 0.0, 0.0, 0.0)
    return PaddingMm.from_list(raw)


def _parse_size_tuple(raw: Any) -> Optional[tuple[float, float]]:
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        raise ValueError('size must be [width_mm, height_mm]')
    w, h = float(raw[0]), float(raw[1])
    return (w, h)


def _parse_element(raw: Mapping[str, Any], *, defaults: TemplateDefaults):
    element_type = str(raw['type'])
    common = dict(
        id=str(raw['id']) if raw.get('id') is not None else None,
        padding_mm=_parse_padding_optional(raw.get('padding_mm')),
        min_size_mm=_parse_size_tuple(raw.get('min_size_mm')),
        max_size_mm=_parse_size_tuple(raw.get('max_size_mm')),
        extensions=dict(raw.get('extensions') or {}),
    )

    if element_type == 'text':
        merged = {**defaults.text_defaults, **raw}
        return TextElement(
            type='text',
            text=str(merged['text']),
            font_height_mm=merged.get('font_height_mm'),
            font_width_mm=merged.get('font_width_mm'),
            wrap=merged.get('wrap'),
            fit=merged.get('fit'),
            max_lines=merged.get('max_lines'),
            align_h=merged.get('align_h'),
            align_v=merged.get('align_v'),
            **common,
        )

    if element_type == 'qr':
        merged_code = {**defaults.code2d_defaults, **raw}
        return QrElement(
            type='qr',
            data=str(merged_code['data']),
            magnification=merged_code.get('magnification'),
            size_mode=merged_code.get('size_mode'),
            align_h=merged_code.get('align_h'),
            align_v=merged_code.get('align_v'),
            error_correction=str(merged_code.get('error_correction', 'M')),
            input_mode=str(merged_code.get('input_mode', 'A')),
            character_mode=merged_code.get('character_mode'),
            quiet_zone_mm=merged_code.get('quiet_zone_mm'),
            render_mode=merged_code.get('render_mode'),
            theme=dict(raw.get('theme') or {}),
            **common,
        )

    if element_type == 'datamatrix':
        merged_code = {**defaults.code2d_defaults, **raw}
        return DataMatrixElement(
            type='datamatrix',
            data=str(merged_code['data']),
            module_size_mm=merged_code.get('module_size_mm'),
            size_mode=merged_code.get('size_mode'),
            align_h=merged_code.get('align_h'),
            align_v=merged_code.get('align_v'),
            quality=int(merged_code.get('quality', 200)),
            columns=int(merged_code.get('columns', 0)),
            rows=int(merged_code.get('rows', 0)),
            format_id=int(merged_code.get('format_id', 6)),
            escape_char=str(merged_code.get('escape_char', '_')),
            quiet_zone_mm=merged_code.get('quiet_zone_mm'),
            render_mode=merged_code.get('render_mode'),
            **common,
        )

    if element_type == 'line':
        return LineElement(
            type='line',
            orientation=str(raw.get('orientation', 'h')),
            thickness_mm=float(raw['thickness_mm']),
            align=str(raw.get('align', 'center')),
            **common,
        )

    if element_type == 'image':
        merged = {**defaults.image_defaults, **raw}
        source_raw = merged.get('source') or {}
        source = ImageSource(
            kind=str(source_raw.get('kind', 'base64')),
            data=str(source_raw.get('data', '')),
        )
        return ImageElement(
            type='image',
            source=source,
            fit=merged.get('fit'),
            align_h=merged.get('align_h'),
            align_v=merged.get('align_v'),
            input_dpi=merged.get('input_dpi'),
            threshold=merged.get('threshold'),
            dither=merged.get('dither'),
            invert=merged.get('invert'),
            **common,
        )

    raise ValueError(f'unsupported element type: {element_type}')
