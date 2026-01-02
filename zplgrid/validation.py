from __future__ import annotations

from typing import Any, Mapping

from .exceptions import TemplateIssue


def validate_template_dict(raw: Mapping[str, Any]) -> list[TemplateIssue]:
    issues: list[TemplateIssue] = []
    if not isinstance(raw, Mapping):
        return [TemplateIssue(path='$', message='template must be a JSON object')]

    issues.extend(_validate_against_jsonschema(raw))
    if issues:
        return issues

    seen_aliases: set[str] = set()
    _validate_node(raw['layout'], issues=issues, path='$.layout', seen_aliases=seen_aliases)
    return issues


def _validate_against_jsonschema(raw: Mapping[str, Any]) -> list[TemplateIssue]:
    try:
        import json
        import importlib.resources as resources
        from jsonschema import Draft202012Validator
    except Exception:
        return []

    try:
        schema_text = resources.files('zplgrid.schemas').joinpath('zplgrid_template_v1.schema.json').read_text(encoding='utf-8')
        schema = json.loads(schema_text)
    except Exception:
        return []

    validator = Draft202012Validator(schema)
    issues: list[TemplateIssue] = []
    for e in sorted(validator.iter_errors(raw), key=lambda x: list(x.absolute_path)):
        path = '$'
        for p in e.absolute_path:
            if isinstance(p, int):
                path += f'[{p}]'
            else:
                path += f'.{p}'
        issues.append(TemplateIssue(path=path, message=e.message))
    return issues


def _validate_node(node: Mapping[str, Any], *, issues: list[TemplateIssue], path: str, seen_aliases: set[str]) -> None:
    kind = node['kind']

    alias = node.get('alias')
    if alias is not None:
        if alias in seen_aliases:
            issues.append(TemplateIssue(path=f'{path}.alias', message=f'duplicate alias: {alias!r}'))
        else:
            seen_aliases.add(alias)

    if kind == 'split':
        gutter = float(node.get('gutter_mm', 0.0))
        divider = node.get('divider') or {}
        if divider and divider.get('visible', False):
            thickness = float(divider.get('thickness_mm', 0.3))
            if gutter < thickness:
                issues.append(TemplateIssue(path=f'{path}.divider', message='gutter_mm must be >= divider.thickness_mm when divider is visible'))

        children = node['children']
        _validate_node(children[0], issues=issues, path=f'{path}.children[0]', seen_aliases=seen_aliases)
        _validate_node(children[1], issues=issues, path=f'{path}.children[1]', seen_aliases=seen_aliases)
        return

    if kind == 'leaf':
        elements = node.get('elements') or []
        for idx, element in enumerate(elements):
            if isinstance(element, Mapping):
                _validate_element(element, issues=issues, path=f'{path}.elements[{idx}]')
        return


def _validate_element(element: Mapping[str, Any], *, issues: list[TemplateIssue], path: str) -> None:
    element_type = element.get('type')
    if element_type == 'qr':
        if 'model' in element:
            issues.append(TemplateIssue(path=f'{path}.model', message='qr model is fixed to 2 and is not configurable'))
        _validate_int_range(element.get('magnification'), issues=issues, path=f'{path}.magnification', minimum=1, maximum=10)
        _validate_enum(element.get('size_mode'), issues=issues, path=f'{path}.size_mode', allowed={'fixed', 'max'})
        _validate_enum(element.get('align_h'), issues=issues, path=f'{path}.align_h', allowed={'left', 'center', 'right'})
        _validate_enum(element.get('align_v'), issues=issues, path=f'{path}.align_v', allowed={'top', 'center', 'bottom'})
        _validate_enum(element.get('error_correction'), issues=issues, path=f'{path}.error_correction', allowed={'L', 'M', 'Q', 'H'})
        _validate_enum(element.get('input_mode'), issues=issues, path=f'{path}.input_mode', allowed={'A', 'M'})
        _validate_enum(element.get('character_mode'), issues=issues, path=f'{path}.character_mode', allowed={'N', 'A'})
        _validate_number_min(element.get('quiet_zone_mm'), issues=issues, path=f'{path}.quiet_zone_mm', minimum=0.0)
        _validate_enum(element.get('render_mode'), issues=issues, path=f'{path}.render_mode', allowed={'zpl', 'image'})

        theme = element.get('theme')
        if theme is not None:
            if not isinstance(theme, Mapping):
                issues.append(TemplateIssue(path=f'{path}.theme', message='must be an object'))
            else:
                _validate_enum(theme.get('preset'), issues=issues, path=f'{path}.theme.preset', allowed={'classic', 'dots', 'rounded'})
                _validate_enum(theme.get('module_shape'), issues=issues, path=f'{path}.theme.module_shape', allowed={'square', 'circle', 'rounded'})
                _validate_enum(theme.get('finder_shape'), issues=issues, path=f'{path}.theme.finder_shape', allowed={'square', 'circle', 'rounded'})

        input_mode = element.get('input_mode')
        has_character_mode = 'character_mode' in element and element.get('character_mode') is not None
        if input_mode == 'M' and not has_character_mode:
            issues.append(TemplateIssue(path=f'{path}.character_mode', message='character_mode is required when input_mode is "M"'))
        if has_character_mode and input_mode != 'M':
            issues.append(TemplateIssue(path=f'{path}.character_mode', message='character_mode is only valid when input_mode is "M"'))
        return

    if element_type == 'datamatrix':
        _validate_number_min(element.get('module_size_mm'), issues=issues, path=f'{path}.module_size_mm', minimum=0.0, exclusive=True)
        _validate_enum(element.get('size_mode'), issues=issues, path=f'{path}.size_mode', allowed={'fixed', 'max'})
        _validate_enum(element.get('align_h'), issues=issues, path=f'{path}.align_h', allowed={'left', 'center', 'right'})
        _validate_enum(element.get('align_v'), issues=issues, path=f'{path}.align_v', allowed={'top', 'center', 'bottom'})
        _validate_enum(element.get('quality'), issues=issues, path=f'{path}.quality', allowed={200})
        _validate_int_range(element.get('columns'), issues=issues, path=f'{path}.columns', minimum=0, maximum=49)
        _validate_int_range(element.get('rows'), issues=issues, path=f'{path}.rows', minimum=0, maximum=49)
        _validate_int_range(element.get('format_id'), issues=issues, path=f'{path}.format_id', minimum=0, maximum=6)
        _validate_string_len(element.get('escape_char'), issues=issues, path=f'{path}.escape_char', length=1)
        _validate_number_min(element.get('quiet_zone_mm'), issues=issues, path=f'{path}.quiet_zone_mm', minimum=0.0)
        _validate_enum(element.get('render_mode'), issues=issues, path=f'{path}.render_mode', allowed={'zpl', 'image'})
        return

    if element_type == 'image':
        source = element.get('source') or {}
        if not isinstance(source, Mapping):
            issues.append(TemplateIssue(path=f'{path}.source', message='must be an object'))
        else:
            _validate_enum(source.get('kind'), issues=issues, path=f'{path}.source.kind', allowed={'base64', 'url'})
            if source.get('data') is None:
                issues.append(TemplateIssue(path=f'{path}.source.data', message='is required'))

        _validate_enum(element.get('fit'), issues=issues, path=f'{path}.fit', allowed={'none', 'contain', 'cover', 'stretch'})
        _validate_enum(element.get('align_h'), issues=issues, path=f'{path}.align_h', allowed={'left', 'center', 'right'})
        _validate_enum(element.get('align_v'), issues=issues, path=f'{path}.align_v', allowed={'top', 'center', 'bottom'})
        _validate_int_range(element.get('input_dpi'), issues=issues, path=f'{path}.input_dpi', minimum=1)
        _validate_int_range(element.get('threshold'), issues=issues, path=f'{path}.threshold', minimum=0, maximum=255)
        _validate_enum(element.get('dither'), issues=issues, path=f'{path}.dither', allowed={'none', 'floyd_steinberg', 'bayer'})
        return


def _validate_enum(value: Any, *, issues: list[TemplateIssue], path: str, allowed: set[Any]) -> None:
    if value is None:
        return
    if value not in allowed:
        issues.append(TemplateIssue(path=path, message=f'must be one of {sorted(allowed)!r}'))


def _validate_int_range(value: Any, *, issues: list[TemplateIssue], path: str, minimum: int | None = None, maximum: int | None = None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        issues.append(TemplateIssue(path=path, message='must be an integer'))
        return
    if minimum is not None and value < minimum:
        issues.append(TemplateIssue(path=path, message=f'must be >= {minimum}'))
    if maximum is not None and value > maximum:
        issues.append(TemplateIssue(path=path, message=f'must be <= {maximum}'))


def _validate_number_min(value: Any, *, issues: list[TemplateIssue], path: str, minimum: float, exclusive: bool = False) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.append(TemplateIssue(path=path, message='must be a number'))
        return
    if exclusive and value <= minimum:
        issues.append(TemplateIssue(path=path, message=f'must be > {minimum}'))
    if not exclusive and value < minimum:
        issues.append(TemplateIssue(path=path, message=f'must be >= {minimum}'))


def _validate_string_len(value: Any, *, issues: list[TemplateIssue], path: str, length: int) -> None:
    if value is None:
        return
    if not isinstance(value, str) or len(value) != length:
        issues.append(TemplateIssue(path=path, message=f'must be a string of length {length}'))
