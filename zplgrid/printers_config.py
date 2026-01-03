from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

_CONFIG_VERSION = 1
_CONFIG_DIR = Path('configs')
_PRINTERS_CONFIG_PATH = _CONFIG_DIR / 'printers.yml'


def _load_schema() -> dict[str, Any]:
    import importlib.resources as resources

    schema_text = resources.files('zplgrid.schemas').joinpath('printers_v1.schema.json').read_text(encoding='utf-8')
    return json.loads(schema_text)


def _format_validation_errors(errors: list[Exception]) -> str:
    parts: list[str] = []
    for err in errors:
        path = '$'
        for p in getattr(err, 'absolute_path', []):
            if isinstance(p, int):
                path += f'[{p}]'
            else:
                path += f'.{p}'
        message = getattr(err, 'message', str(err))
        parts.append(f'{path}: {message}')
    return '; '.join(parts)


def _validate_printers_config(raw: Mapping[str, Any]) -> None:
    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(raw), key=lambda e: list(e.absolute_path))
    if errors:
        raise ValueError(_format_validation_errors(errors))

    printers = raw.get('printers') or []
    seen_ids: set[str] = set()
    for idx, printer in enumerate(printers):
        printer_id = printer.get('id')
        if not isinstance(printer_id, str) or not printer_id:
            raise ValueError(f'$.printers[{idx}].id: must be a non-empty string')
        if printer_id in seen_ids:
            raise ValueError(f'$.printers[{idx}].id: duplicate id {printer_id!r}')
        seen_ids.add(printer_id)


def load_printers_config(path: Path | None = None) -> dict[str, Any]:
    target = path or _PRINTERS_CONFIG_PATH
    if not target.exists():
        return {'config_version': _CONFIG_VERSION, 'printers': []}

    with target.open('r', encoding='utf-8') as handle:
        raw = yaml.safe_load(handle)

    if raw is None:
        return {'config_version': _CONFIG_VERSION, 'printers': []}
    if not isinstance(raw, Mapping):
        raise ValueError('printers.yml must be a YAML object')

    normalized = dict(raw)
    _validate_printers_config(normalized)
    return normalized


def save_printers_config(config: Mapping[str, Any], path: Path | None = None) -> None:
    normalized = dict(config)
    _validate_printers_config(normalized)

    target = path or _PRINTERS_CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', encoding='utf-8') as handle:
        yaml.safe_dump(normalized, handle, sort_keys=False, allow_unicode=True)
