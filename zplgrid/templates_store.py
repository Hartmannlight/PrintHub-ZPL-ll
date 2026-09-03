from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


_TEMPLATES_DIR = Path(os.getenv('ZPLGRID_TEMPLATES_DIR', 'templates'))
_METADATA_FILENAME = 'metadata.json'
_TEMPLATE_FILENAME = 'template.json'
_SAMPLE_DATA_FILENAME = 'sample_data.json'
_PREVIEW_FILENAME = 'preview.png'
_TEMPLATE_ID_RE = re.compile(r'^[a-z0-9][a-z0-9-]{0,80}$')


@dataclass(frozen=True)
class TemplateEntry:
    template_id: str
    name: str
    tags: list[str]
    variables: list[dict[str, Any]]
    preview_target: dict[str, Any]
    dir_path: Path

    @property
    def metadata_path(self) -> Path:
        return self.dir_path / _METADATA_FILENAME

    @property
    def template_path(self) -> Path:
        return self.dir_path / _TEMPLATE_FILENAME

    @property
    def sample_data_path(self) -> Path:
        return self.dir_path / _SAMPLE_DATA_FILENAME

    @property
    def preview_path(self) -> Path:
        return self.dir_path / _PREVIEW_FILENAME


def ensure_templates_dir() -> Path:
    _TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return _TEMPLATES_DIR


def seed_bundled_templates(source_dir: str | Path | None) -> list[str]:
    """Install missing built-in templates without changing user-owned copies."""
    if not source_dir:
        return []
    source_root = Path(source_dir)
    if not source_root.is_dir():
        raise ValueError(f'bundled templates directory does not exist: {source_root}')

    target_root = ensure_templates_dir()
    installed: list[str] = []
    for source in sorted(source_root.iterdir()):
        if not source.is_dir() or not (source / _METADATA_FILENAME).is_file():
            continue
        template_id = validate_template_id(source.name)
        target = _template_dir(target_root, template_id)
        if target.exists():
            continue
        shutil.copytree(source, target)
        installed.append(template_id)
    return installed


def validate_template_id(template_id: str) -> str:
    if not _TEMPLATE_ID_RE.fullmatch(template_id):
        raise ValueError('template_id must match ^[a-z0-9][a-z0-9-]{0,80}$')
    return template_id


def _template_dir(root: Path, template_id: str) -> Path:
    validated_id = validate_template_id(template_id)
    root_resolved = root.resolve()
    dir_path = (root / validated_id).resolve()
    if dir_path != root_resolved and root_resolved not in dir_path.parents:
        raise ValueError('template_id resolves outside templates directory')
    return dir_path


def _slugify(value: str) -> str:
    normalized = value.strip().lower()
    normalized = re.sub(r'[^a-z0-9]+', '-', normalized)
    normalized = normalized.strip('-')
    return normalized or 'template'


def _unique_template_id(base: str, existing: Iterable[str]) -> str:
    if base not in existing:
        return base
    idx = 2
    while True:
        candidate = f'{base}-{idx}'
        if candidate not in existing:
            return candidate
        idx += 1


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding='utf-8')
        raw = json.loads(text)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def list_templates(*, tags: set[str] | None = None) -> list[TemplateEntry]:
    root = ensure_templates_dir()
    entries: list[TemplateEntry] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        metadata_path = entry / _METADATA_FILENAME
        if not metadata_path.exists():
            continue
        metadata = _load_metadata(metadata_path)
        template_id = str(metadata.get('id') or entry.name)
        name = str(metadata.get('name') or template_id)
        tag_list = [str(tag) for tag in metadata.get('tags') or []]
        variables = [dict(item) for item in (metadata.get('variables') or []) if isinstance(item, Mapping)]
        preview_target = dict(metadata.get('preview_target') or {})
        if tags:
            if not tags.issubset(set(tag_list)):
                continue
        entries.append(
            TemplateEntry(
                template_id=template_id,
                name=name,
                tags=tag_list,
                variables=variables,
                preview_target=preview_target,
                dir_path=entry,
            )
        )
    return entries


def load_template_entry(template_id: str) -> TemplateEntry:
    root = ensure_templates_dir()
    dir_path = _template_dir(root, template_id)
    metadata_path = dir_path / _METADATA_FILENAME
    if not metadata_path.exists():
        raise FileNotFoundError(template_id)
    metadata = _load_metadata(metadata_path)
    name = str(metadata.get('name') or template_id)
    tags = [str(tag) for tag in metadata.get('tags') or []]
    variables = [dict(item) for item in (metadata.get('variables') or []) if isinstance(item, Mapping)]
    preview_target = dict(metadata.get('preview_target') or {})
    return TemplateEntry(
        template_id=template_id,
        name=name,
        tags=tags,
        variables=variables,
        preview_target=preview_target,
        dir_path=dir_path,
    )


def save_template_entry(
    *,
    name: str,
    tags: list[str],
    variables: list[dict[str, Any]],
    preview_target: dict[str, Any],
    template: Mapping[str, Any],
    sample_data: Mapping[str, Any],
    preview_png: bytes | None,
) -> TemplateEntry:
    root = ensure_templates_dir()
    existing_ids = {entry.name for entry in root.iterdir() if entry.is_dir()}
    base_id = _slugify(name)
    template_id = _unique_template_id(base_id, existing_ids)
    validate_template_id(template_id)
    dir_path = _template_dir(root, template_id)
    dir_path.mkdir(parents=True, exist_ok=True)

    metadata = {
        'id': template_id,
        'name': name,
        'tags': tags,
        'variables': variables,
        'preview_target': preview_target,
    }
    (dir_path / _METADATA_FILENAME).write_text(json.dumps(metadata, indent=2, ensure_ascii=True), encoding='utf-8')
    (dir_path / _TEMPLATE_FILENAME).write_text(json.dumps(template, indent=2, ensure_ascii=True), encoding='utf-8')
    (dir_path / _SAMPLE_DATA_FILENAME).write_text(json.dumps(sample_data, indent=2, ensure_ascii=True), encoding='utf-8')
    if preview_png is not None:
        (dir_path / _PREVIEW_FILENAME).write_bytes(preview_png)
    else:
        preview_path = dir_path / _PREVIEW_FILENAME
        if preview_path.exists():
            preview_path.unlink()

    return TemplateEntry(
        template_id=template_id,
        name=name,
        tags=tags,
        variables=variables,
        preview_target=preview_target,
        dir_path=dir_path,
    )


def update_template_entry(
    *,
    template_id: str,
    name: str,
    tags: list[str],
    variables: list[dict[str, Any]],
    preview_target: dict[str, Any],
    template: Mapping[str, Any],
    sample_data: Mapping[str, Any],
    preview_png: bytes | None,
) -> TemplateEntry:
    root = ensure_templates_dir()
    dir_path = _template_dir(root, template_id)
    if not dir_path.exists():
        raise FileNotFoundError(template_id)
    dir_path.mkdir(parents=True, exist_ok=True)

    metadata = {
        'id': template_id,
        'name': name,
        'tags': tags,
        'variables': variables,
        'preview_target': preview_target,
    }
    (dir_path / _METADATA_FILENAME).write_text(json.dumps(metadata, indent=2, ensure_ascii=True), encoding='utf-8')
    (dir_path / _TEMPLATE_FILENAME).write_text(json.dumps(template, indent=2, ensure_ascii=True), encoding='utf-8')
    (dir_path / _SAMPLE_DATA_FILENAME).write_text(json.dumps(sample_data, indent=2, ensure_ascii=True), encoding='utf-8')
    if preview_png is not None:
        (dir_path / _PREVIEW_FILENAME).write_bytes(preview_png)
    else:
        preview_path = dir_path / _PREVIEW_FILENAME
        if preview_path.exists():
            preview_path.unlink()

    return TemplateEntry(
        template_id=template_id,
        name=name,
        tags=tags,
        variables=variables,
        preview_target=preview_target,
        dir_path=dir_path,
    )
