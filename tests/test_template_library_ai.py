from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from zplgrid.api import app
from zplgrid import api, template_ai, templates_store


TEMPLATE = {
    'schema_version': 1,
    'name': 'Cable label',
    'layout': {'kind': 'leaf', 'alias': 'title', 'elements': [
        {'type': 'text', 'text': '{title}', 'font_height_mm': 5},
    ]},
}
TARGET = {'width_mm': 50, 'height_mm': 25, 'dpi': 203, 'origin_x_mm': 0, 'origin_y_mm': 0}


def test_sample_data_and_print_defaults_are_independent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setenv('ZPLGRID_ENABLE_LABELARY_TEMPLATES', '0')
    monkeypatch.setenv('ZPLGRID_PRINT_JOBS_DIR', str(tmp_path / 'jobs'))
    monkeypatch.setenv('PRINTHUB_ADMIN_TOKEN', 'test-admin-token-with-24-chars')
    monkeypatch.delenv('PRINTHUB_ADMIN_TOKEN_FILE', raising=False)
    with TestClient(app) as client:
        created = client.post('/v1/templates', json={
            'name': 'Cable label', 'description': 'For patch cables',
            'usage_context': 'Network rack', 'tags': ['cable'],
            'template': TEMPLATE, 'variables': [{'name': 'title', 'mode': 'required'}],
            'sample_data': {'title': 'EXAMPLE'}, 'print_defaults': {},
            'preview_target': TARGET,
        })
        assert created.status_code == 200, created.text
        detail = created.json()
        assert detail['sample_data'] == {'title': 'EXAMPLE'}
        assert detail['print_defaults'] == {}
        assert detail['description'] == 'For patch cables'
        original_template = (tmp_path / 'templates' / detail['id'] / 'template.json').read_bytes()
        changed = client.patch(f"/v1/templates/{detail['id']}/metadata", json={'favorite': True, 'archived': True})
        assert changed.status_code == 200, changed.text
        assert changed.json()['favorite'] is True
        assert changed.json()['archived'] is True
        assert (tmp_path / 'templates' / detail['id'] / 'template.json').read_bytes() == original_template
        assert client.get(f"/v1/templates/{detail['id']}").json()['print_defaults'] == {}
        assert client.get('/v1/template-preview-settings').json()['stored_enabled'] is False
        disabled = client.post('/v1/templates/previews/regenerate', headers={
            'Authorization': 'Bearer test-admin-token-with-24-chars',
        }, json={'template_ids': [detail['id']]})
        assert disabled.status_code == 409
        monkeypatch.setenv('ZPLGRID_ENABLE_LABELARY_TEMPLATES', '1')
        monkeypatch.setattr(api, 'render_labelary_png_bytes', lambda *_args, **_kwargs: b'fake-png')
        regenerated = client.post('/v1/templates/previews/regenerate', headers={
            'Authorization': 'Bearer test-admin-token-with-24-chars',
        }, json={'template_ids': [detail['id']]})
        assert regenerated.status_code == 200, regenerated.text
        assert regenerated.json()['regenerated'] == [detail['id']]
        assert client.get(f"/v1/templates/{detail['id']}/preview").content == b'fake-png'
        def fail_render(*_args, **_kwargs):
            raise RuntimeError('renderer unavailable')
        monkeypatch.setattr(api, 'render_labelary_png_bytes', fail_render)
        failed = client.post('/v1/templates/previews/regenerate', headers={
            'Authorization': 'Bearer test-admin-token-with-24-chars',
        }, json={'template_ids': [detail['id']]})
        assert failed.json()['failed'] == {detail['id']: 'renderer unavailable'}
        assert client.get(f"/v1/templates/{detail['id']}/preview").content == b'fake-png'


def test_old_template_starts_print_form_empty(tmp_path, monkeypatch) -> None:
    root = tmp_path / 'templates'
    directory = root / 'older'
    directory.mkdir(parents=True)
    (directory / 'metadata.json').write_text(json.dumps({'name': 'Older'}), encoding='utf-8')
    (directory / 'sample_data.json').write_text(json.dumps({'title': 'Legacy'}), encoding='utf-8')
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', root)
    assert templates_store.load_template_entry('older').print_defaults == {}


def test_saving_survives_thumbnail_service_failure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setenv('ZPLGRID_ENABLE_LABELARY_TEMPLATES', '1')
    monkeypatch.setenv('ZPLGRID_PRINT_JOBS_DIR', str(tmp_path / 'jobs'))
    def fail_render(*_args, **_kwargs):
        raise RuntimeError('thumbnail service unavailable')
    monkeypatch.setattr(api, 'render_labelary_png_bytes', fail_render)
    body = {
        'name': 'Cable label', 'template': TEMPLATE,
        'variables': [{'name': 'title', 'mode': 'required'}],
        'sample_data': {'title': 'EXAMPLE'}, 'print_defaults': {},
        'preview_target': TARGET,
    }
    with TestClient(app) as client:
        created = client.post('/v1/templates', json=body)
        assert created.status_code == 200, created.text
        template_id = created.json()['id']
        assert created.json()['preview_available'] is False
        assert 'thumbnail service unavailable' in created.json()['preview_warning']
        def timeout_render(*_args, **_kwargs):
            raise api.requests.Timeout('thumbnail request timed out')
        monkeypatch.setattr(api, 'render_labelary_png_bytes', timeout_render)
        updated = client.put(f'/v1/templates/{template_id}', json={**body, 'description': 'Updated'})
        assert updated.status_code == 200, updated.text
        assert updated.json()['description'] == 'Updated'
        assert updated.json()['preview_available'] is False
        assert 'thumbnail request timed out' in updated.json()['preview_warning']


def test_ai_draft_has_sample_preview_with_live_preview_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setenv('ZPLGRID_ENABLE_LABELARY_TEMPLATES', '1')
    monkeypatch.setenv('ZPLGRID_ENABLE_LABELARY_API', '0')
    monkeypatch.setenv('PRINTHUB_ADMIN_TOKEN', 'test-admin-token-with-24-chars')
    monkeypatch.delenv('PRINTHUB_ADMIN_TOKEN_FILE', raising=False)
    monkeypatch.setenv('ZPLGRID_PRINT_JOBS_DIR', str(tmp_path / 'jobs'))
    monkeypatch.setattr(api, 'generate_template_draft', lambda *_args, **_kwargs: {
        'name': 'Cable label', 'description': '', 'usage_context': '', 'tags': [],
        'variables': [{'name': 'title', 'mode': 'required'}],
        'sample_data': {'title': 'EXAMPLE'}, 'template': TEMPLATE, 'reference_ids': [],
    })
    monkeypatch.setattr(api, 'render_labelary_png_bytes', lambda *_args, **_kwargs: b'fake-png')
    with TestClient(app) as client:
        response = client.post('/v1/template-assistant/generate', headers={
            'Authorization': 'Bearer test-admin-token-with-24-chars',
        }, json={'prompt': 'Make a cable label', 'target': TARGET})
        assert response.status_code == 200, response.text
        assert response.json()['preview_png_base64'] == 'ZmFrZS1wbmc='
        assert response.json()['preview_error'] is None


def test_ai_draft_uses_openrouter_and_is_not_saved(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setenv('ZPLGRID_ENABLE_LABELARY_TEMPLATES', '0')
    monkeypatch.setenv('PRINTHUB_AI_API_KEY', 'test-only-key')
    monkeypatch.setenv('PRINTHUB_ADMIN_TOKEN', 'test-admin-token-with-24-chars')
    monkeypatch.delenv('PRINTHUB_ADMIN_TOKEN_FILE', raising=False)
    monkeypatch.setenv('ZPLGRID_PRINT_JOBS_DIR', str(tmp_path / 'jobs'))
    requests_seen = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'message': {'content': json.dumps({
                'name': 'Cable label', 'description': 'Cable ID', 'usage_context': 'Rack',
                'tags': ['cable'], 'variables_json': json.dumps([{'name': 'title', 'mode': 'required'}]),
                'sample_data_json': json.dumps({'title': 'EXAMPLE'}),
                'template_json': json.dumps(TEMPLATE),
            })}}]}

    def fake_post(url, **kwargs):
        requests_seen.append((url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(template_ai.requests, 'post', fake_post)
    with TestClient(app) as client:
        denied = client.post('/v1/template-assistant/generate', json={
            'prompt': 'Make a cable label', 'target': TARGET, 'use_existing': False,
        })
        assert denied.status_code == 401
        generated = client.post('/v1/template-assistant/generate', headers={
            'Authorization': 'Bearer test-admin-token-with-24-chars',
        }, json={'prompt': 'Make a cable label', 'target': TARGET, 'use_existing': False})
        assert generated.status_code == 200, generated.text
        assert generated.json()['print_defaults'] == {}
        assert generated.json()['sample_data'] == {'title': 'EXAMPLE'}
        assert client.get('/v1/templates').json() == []

    url, kwargs = requests_seen[0]
    assert url == 'https://openrouter.ai/api/v1/chat/completions'
    assert kwargs['json']['provider']['require_parameters'] is True
    assert kwargs['json']['response_format']['type'] == 'json_schema'
    assert kwargs['headers']['Authorization'] == 'Bearer test-only-key'


def test_ai_search_uses_context_without_sending_sample_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', tmp_path / 'templates')
    entry = templates_store.save_template_entry(
        name='Cable flag', description='Marks patch cables', usage_context='Network rack',
        tags=['cable'], variables=[{'name': 'title'}], preview_target=TARGET,
        template=TEMPLATE, sample_data={'title': 'PRIVATE SAMPLE'},
        print_defaults={}, preview_png=None,
    )
    matches = template_ai._search_references('Create a network rack cable label', [])
    assert [item.template_id for item in matches] == [entry.template_id]
    reference = template_ai._reference_payload(matches[0])
    assert reference['usage_context'] == 'Network rack'
    assert 'PRIVATE SAMPLE' not in json.dumps(reference)


def test_ai_shares_only_explicitly_selected_references(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(templates_store, '_TEMPLATES_DIR', tmp_path / 'templates')
    monkeypatch.setenv('PRINTHUB_AI_API_KEY', 'test-only-key')
    entry = templates_store.save_template_entry(
        name='Cable flag', description='Marks patch cables', usage_context='Network rack',
        tags=['cable'], variables=[{'name': 'title'}], preview_target=TARGET,
        template=TEMPLATE, sample_data={'title': 'PRIVATE SAMPLE'},
        print_defaults={}, preview_png=None,
    )
    contexts = []
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'choices': [{'message': {'content': json.dumps({
                'name': 'Cable label', 'description': '', 'usage_context': '',
                'tags': [], 'variables_json': '[]', 'sample_data_json': '{}',
                'template_json': json.dumps(TEMPLATE),
            })}}]}

    def fake_post(_url, **kwargs):
        contexts.append(json.loads(kwargs['json']['messages'][1]['content']))
        return FakeResponse()

    monkeypatch.setattr(template_ai.requests, 'post', fake_post)
    template_ai.generate_template_draft('Cable label for a rack', width_mm=50, height_mm=25,
                                        dpi=203, use_existing=True, reference_ids=[])
    template_ai.generate_template_draft('Cable label for a rack', width_mm=50, height_mm=25,
                                        dpi=203, use_existing=True, reference_ids=[entry.template_id])
    assert contexts[0]['reference_templates'] == []
    assert [item['id'] for item in contexts[1]['reference_templates']] == [entry.template_id]


def test_ai_rejects_blank_thumbnail_samples(monkeypatch) -> None:
    monkeypatch.setattr(api, 'generate_template_draft', lambda *_args, **_kwargs: {
        'name': 'Cable label', 'description': '', 'usage_context': '', 'tags': [],
        'variables': [{'name': 'title', 'mode': 'required'}],
        'sample_data': {'title': ''}, 'template': TEMPLATE, 'reference_ids': [],
    })
    with pytest.raises(HTTPException) as error:
        api.generate_template_with_ai(api.TemplateAIGenerateRequest(
            prompt='Make a cable label', target=api.RenderTarget(**TARGET), use_existing=False,
        ))
    assert error.value.status_code == 502
    assert 'blank sample values' in error.value.detail
