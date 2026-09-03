from __future__ import annotations

import json
from pathlib import Path

from zplgrid import templates_store
from zplgrid.model import LabelTarget
from zplgrid.parser import load_template


def _write_bundled_template(root: Path, template_id: str, name: str) -> None:
    directory = root / template_id
    directory.mkdir(parents=True)
    (directory / 'metadata.json').write_text(
        json.dumps({'id': template_id, 'name': name}),
        encoding='utf-8',
    )
    (directory / 'template.json').write_text('{}', encoding='utf-8')


def test_seed_bundled_templates_adds_missing_and_preserves_existing(tmp_path, monkeypatch) -> None:
    source = tmp_path / 'bundled'
    destination = tmp_path / 'user-templates'
    _write_bundled_template(source, 'briefadresse', 'Bundled address')
    existing = destination / 'briefadresse'
    existing.mkdir(parents=True)
    (existing / 'metadata.json').write_text('{"name":"User address"}', encoding='utf-8')
    _write_bundled_template(source, 'another-template', 'Another template')
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', destination)

    installed = templates_store.seed_bundled_templates(source)

    assert installed == ['another-template']
    assert json.loads((existing / 'metadata.json').read_text(encoding='utf-8'))['name'] == 'User address'
    assert (destination / 'another-template' / 'template.json').is_file()


def test_bundled_address_template_renders_pasted_lines() -> None:
    directory = Path(__file__).parents[1] / 'templates' / 'briefadresse'
    template = load_template(json.loads((directory / 'template.json').read_text(encoding='utf-8')))

    zpl = template.compile(
        target=LabelTarget(width_mm=72, height_mm=26, dpi=203),
        variables={'address': 'Erika Mustermann\nMusterstrasse 17\n51147 Koeln'},
    )

    assert '^FDErika Mustermann' in zpl
    assert '^FDMusterstrasse 17' in zpl
    assert '^FD51147 Koeln' in zpl
