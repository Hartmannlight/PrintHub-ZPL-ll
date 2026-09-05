from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import pytest
import yaml
from fastapi.testclient import TestClient

from zplgrid import api, printer_discovery, zebra_tamer
from zplgrid.fleet.legacy import LegacyFleetAdapter
from zplgrid.printer_registry import PrinterRegistry, RegistryConflict


def printer(printer_id='existing-id', agent_id='pi-a', url='http://agent-a:8080'):
    connection = {'protocol': 'zebra_tamer', 'base_url': url, 'printer_id': 'zebra-usb', 'timeout_ms': 10000}
    if agent_id:
        connection['agent_id'] = agent_id
    return {'id': printer_id, 'name': 'My calibrated printer', 'model': 'Zebra', 'vendor': 'Zebra', 'driver': 'zpl',
            'connection': connection, 'media': {'loaded': {'width_mm': 70, 'height_mm': 30, 'color': 'white', 'type': 'thermal'}},
            'alignment': {'dpi': 300, 'offset_x_mm': 2, 'offset_y_mm': 1}, 'zpl': {'darkness': 15, 'print_speed': 2},
            'defaults': {'copies': 2, 'rotation': 90}, 'capabilities': {'supports_status': True, 'supports_graphics': True, 'supports_cut': False},
            'enabled': False}


@pytest.fixture
def registry(tmp_path):
    seed = tmp_path / 'printers.yml'
    seed.write_text(yaml.safe_dump({'config_version': 1, 'printers': [printer()]}), encoding='utf-8')
    registry = PrinterRegistry(tmp_path / 'printers.sqlite3', seed)
    registry.initialize()
    return registry


def test_seed_import_is_once_and_yaml_is_not_written(registry):
    original = registry.seed_path.read_bytes()
    item = registry.get('existing-id')
    registry.patch(item['id'], {'name': 'Edited in Studio'}, item['registry']['revision'])
    assert registry.seed_path.read_bytes() == original
    registry.seed_path.write_text('not: valid: yaml', encoding='utf-8')
    restarted = PrinterRegistry(registry.path, registry.seed_path)
    restarted.initialize()
    assert restarted.get('existing-id')['name'] == 'Edited in Studio'
    assert restarted.get('existing-id')['alignment']['dpi'] == 300


def test_driver_agent_profile_does_not_require_zpl_settings(tmp_path):
    registry = PrinterRegistry(tmp_path / 'drivers.sqlite3', tmp_path / 'absent.yml')
    registry.initialize()
    profile = printer('niimbot-b1')
    profile['driver'] = 'niimbot_b1'
    profile['vendor'] = 'Niimbot'
    profile['model'] = 'B1'
    profile['connection'] = {
        'protocol': 'driver_agent',
        'base_url': 'http://niimbot-agent:8080',
        'printer_id': 'b1-usb',
        'agent_id': 'pi-labels',
        'timeout_ms': 10000,
    }
    profile.pop('zpl')
    profile['driver_options'] = {'compression': 'auto'}

    created = registry.create(profile)

    assert created['driver'] == 'niimbot_b1'
    assert 'zpl' not in created
    assert created['driver_options'] == {'compression': 'auto'}


def test_registration_preserves_all_existing_settings(registry):
    incoming = printer()
    incoming.update(name='Factory name', enabled=True)
    incoming['alignment']['dpi'] = 203
    incoming['media']['loaded']['width_mm'] = 50
    existing = registry.register(incoming)
    assert existing['id'] == 'existing-id'
    assert registry.export()['printers'] == [printer()]


def test_same_local_id_on_different_agents_has_distinct_public_ids(registry):
    second = registry.register(printer(agent_id='pi-b', url='http://agent-b:8080'))
    assert second['id'] != 'existing-id'
    assert len(registry.list()) == 2
    assert registry.get('existing-id')['connection']['base_url'] == 'http://agent-a:8080'


def test_legacy_put_cannot_overwrite_or_duplicate(registry):
    assert registry.create(printer())['id'] == 'existing-id'
    with pytest.raises(RegistryConflict):
        registry.create(printer(agent_id='pi-b', url='http://agent-b:8080'))
    with pytest.raises(RegistryConflict):
        registry.create(printer(printer_id='different-public-id'))
    assert len(registry.list()) == 1


def test_verified_ip_change_preserves_public_id_and_settings(registry):
    updated = registry.observe('http://new-ip:8080', 'zebra-usb', 'pi-a')
    assert updated['id'] == 'existing-id'
    assert updated['connection']['base_url'] == 'http://new-ip:8080'
    assert updated['alignment'] == printer()['alignment']
    assert updated['enabled'] is False
    assert updated['discovery']['available'] is True
    assert updated['registry']['revision'] == 2


@pytest.mark.parametrize('agent_id', ['pi-b', None])
def test_reused_ip_or_identity_downgrade_cannot_redirect(registry, agent_id):
    with pytest.raises(RegistryConflict):
        registry.observe('http://agent-a:8080', 'zebra-usb', agent_id)
    assert registry.export()['printers'] == [printer()]


def test_legacy_agent_upgrade_binds_identity_without_renaming(tmp_path):
    registry = PrinterRegistry(tmp_path / 'registry.sqlite3', tmp_path / 'absent.yml')
    registry.initialize()
    registry.create(printer(agent_id=None))
    result = registry.observe('http://agent-a:8080', 'zebra-usb', 'pi-a')
    assert result['id'] == 'existing-id'
    assert result['connection']['agent_id'] == 'pi-a'
    assert result['alignment']['dpi'] == 300


def test_conflicting_endpoint_and_identity_are_not_merged(registry):
    registry.create(printer('legacy-copy', agent_id=None, url='http://other-ip:8080'))
    with pytest.raises(RegistryConflict):
        registry.observe('http://other-ip:8080', 'zebra-usb', 'pi-a')
    assert len(registry.list()) == 2


def test_edit_revision_prevents_lost_updates(registry):
    registry.patch('existing-id', {'name': 'New name'}, 1)
    with pytest.raises(RegistryConflict):
        registry.patch('existing-id', {'enabled': True}, 1)
    assert registry.get('existing-id')['enabled'] is False
    with pytest.raises(ValueError):
        registry.patch('existing-id', {'connection': printer()['connection']}, 2)


def test_import_conflict_rolls_back_entire_batch(registry):
    new = printer('new-id', agent_id='pi-b', url='http://agent-b:8080')
    changed = printer()
    changed['name'] = 'Overwrite'
    with pytest.raises(RegistryConflict):
        registry.import_config({'config_version': 1, 'printers': [new, changed]})
    assert registry.export()['printers'] == [printer()]


def test_export_can_be_reimported_without_runtime_metadata(registry):
    exported = registry.export()
    assert 'registry' not in exported['printers'][0]
    assert 'discovery' not in exported['printers'][0]
    registry.import_config(exported)
    assert registry.export() == exported


def test_concurrent_registration_is_idempotent(registry):
    new = printer(agent_id='pi-b', url='http://agent-b:8080')
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: registry.register(new)['id'], range(8)))
    assert len(set(ids)) == 1
    assert len(registry.list()) == 2


def test_failed_seed_migration_is_atomic_and_retryable(tmp_path):
    seed = tmp_path / 'printers.yml'
    config = {'config_version': 1, 'printers': [printer(), printer('duplicate')]}
    seed.write_text(yaml.safe_dump(config), encoding='utf-8')
    registry = PrinterRegistry(tmp_path / 'registry.sqlite3', seed)
    with pytest.raises(RegistryConflict):
        registry.initialize()
    config['printers'].pop()
    seed.write_text(yaml.safe_dump(config), encoding='utf-8')
    registry.initialize()
    assert len(registry.list()) == 1


def test_discovery_updates_endpoint_but_does_not_register_unknown(registry, monkeypatch):
    monkeypatch.setattr(printer_discovery, 'discover_agent_urls', lambda: ['http://new-ip:8080'])
    def inspect(url):
        if url == 'http://agent-a:8080':
            raise RuntimeError('offline')
        return {'base_url': url, 'agent_id': 'pi-a', 'available': True, 'printers': [{'id': 'zebra-usb'}, {'id': 'new-device'}]}
    monkeypatch.setattr(printer_discovery, 'inspect_agent', inspect)
    result = printer_discovery.discover_printers(registry)
    assert result['agents'][1]['printers'][0]['registered_id'] == 'existing-id'
    assert result['agents'][1]['printers'][1]['registered_id'] is None
    assert len(registry.list()) == 1
    assert registry.get('existing-id')['connection']['base_url'] == 'http://new-ip:8080'
    assert registry.get('existing-id')['discovery']['available'] is True


def test_offline_printers_remain_registered(registry, monkeypatch):
    monkeypatch.setattr(printer_discovery, 'discover_agent_urls', lambda: [])
    monkeypatch.setattr(printer_discovery, 'inspect_agent', lambda _: (_ for _ in ()).throw(RuntimeError('offline')))
    printer_discovery.discover_printers(registry)
    assert registry.get('existing-id')['discovery']['available'] is False
    assert registry.get('existing-id')['enabled'] is False


def test_aliases_are_deduplicated_by_agent_identity(registry, monkeypatch):
    monkeypatch.setattr(printer_discovery, 'discover_agent_urls', lambda: ['http://another-address:8080'])
    monkeypatch.setattr(printer_discovery, 'inspect_agent', lambda url: {'base_url': url, 'agent_id': 'pi-a', 'available': True, 'printers': [{'id': 'zebra-usb'}]})
    result = printer_discovery.discover_printers(registry)
    assert len(result['agents']) == 1
    assert result['agents'][0]['aliases'] == ['http://another-address:8080']


def test_identity_is_verified_before_any_print_post(monkeypatch):
    monkeypatch.setattr(zebra_tamer, 'get_agent_info', lambda _: {'agent_id': 'imposter'})
    monkeypatch.setattr(zebra_tamer.requests, 'post', lambda *a, **k: pytest.fail('Must not print'))
    with pytest.raises(RuntimeError, match='identity mismatch'):
        zebra_tamer.submit_zpl(printer()['connection'], '^XA^XZ')


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(api.app.state, 'printer_registry', registry, raising=False)
    monkeypatch.setattr(api.app.state, 'fleet_port', LegacyFleetAdapter(registry), raising=False)
    def offline(_):
        raise RuntimeError('test agent is offline')
    monkeypatch.setattr('zplgrid.printer_media.get_configuration', offline)
    return TestClient(api.app)  # No lifespan: never touch real jobs or registry files.


def test_agent_device_and_media_edits_are_rejected_at_registry_boundary(registry):
    for field in ('media', 'alignment', 'zpl'):
        with pytest.raises(ValueError, match='exclusively in ZebraTamer'):
            registry.patch('existing-id', {field:printer()[field]}, 1)
    assert registry.get('existing-id')['registry']['revision'] == 1


def test_registration_reads_agent_media_instead_of_client_defaults(client, monkeypatch):
    monkeypatch.setattr(api, 'inspect_agent', lambda _: {'base_url':'http://agent-b:8080', 'agent_id':'pi-b', 'printers':[{'id':'new'}]})
    monkeypatch.setattr('zplgrid.printer_media.get_configuration', lambda _: {'media': {'state': {'media': {'width_mm':60, 'height_mm':30, 'color':{'name':'Blue'}, 'print_technology':'thermal_transfer'}}},
        'device': {'profile': {'resolution_dpi':300}}})
    response = client.post('/v1/printers/register', json={'base_url':'http://agent-b:8080', 'printer_id':'new', 'width_mm':1, 'height_mm':1, 'dpi':203})
    assert response.status_code == 200, response.text
    assert response.json()['media']['loaded']['color'] == 'Blue'
    assert response.json()['alignment']['dpi'] == 300
    assert response.json()['zpl'] == {}


def test_raw_print_without_preview_does_not_require_media_after_dispatch(client, registry, monkeypatch):
    from zplgrid.fleet.ports import DeliveryReceipt, DeliveryState

    class FakeFleet:
        def get_printer(self, printer_id):
            return registry.get(printer_id)

        def deliver(self, *_args, **_kwargs):
            return DeliveryReceipt(
                bytes_accepted=8,
                delivery_id='test-job',
                state=DeliveryState.QUEUED,
                downstream_state='queued',
            )

    client.patch('/v1/printers/existing-id', json={'revision':1, 'settings':{'enabled':True}})
    monkeypatch.setattr(api, '_fleet', lambda: FakeFleet())
    response = client.post('/v1/printers/existing-id/prints/zpl', json={'zpl':'^XA^XZ', 'return_preview':False})
    assert response.status_code == 200, response.text
    assert response.json()['job_id'] == 'test-job'


def test_api_conflicts_and_revision_checked_settings(client):
    replacement = printer(agent_id='pi-b', url='http://agent-b:8080')
    assert client.put('/v1/printers/existing-id', json=replacement).status_code == 409
    response = client.patch('/v1/printers/existing-id', json={'revision': 1, 'settings': {'name': 'Studio edit'}})
    assert response.status_code == 200
    assert response.json()['name'] == 'Studio edit'
    assert client.patch('/v1/printers/existing-id', json={'revision': 1, 'settings': {'enabled': True}}).status_code == 409


def test_api_registration_does_not_reset_existing_profile(client, monkeypatch):
    monkeypatch.setattr(api, 'inspect_agent', lambda _: {'base_url': 'http://agent-a:8080', 'agent_id': 'pi-a', 'printers': [{'id': 'zebra-usb'}]})
    response = client.post('/v1/printers/register', json={'base_url': 'http://agent-a:8080', 'printer_id': 'zebra-usb', 'width_mm': 50, 'height_mm': 25, 'dpi': 203})
    assert response.status_code == 200
    assert response.json()['id'] == 'existing-id'
    assert response.json()['alignment']['dpi'] == 300
    assert response.json()['enabled'] is False


def test_api_export_import_and_default(client, monkeypatch):
    exported = client.get('/v1/printer-registry/export')
    assert exported.status_code == 200
    assert client.post('/v1/printer-registry/import', json=yaml.safe_load(exported.text)).status_code == 200
    assert client.get('/v1/printers').json()['default_printer_id'] is None
    client.patch('/v1/printers/existing-id', json={'revision': 1, 'settings': {'enabled': True}})
    monkeypatch.setenv('ZPLGRID_DEFAULT_PRINTER_ID', 'existing-id')
    assert client.get('/v1/printers').json()['default_printer_id'] == 'existing-id'


def test_registration_rejects_identity_change_after_discovery(client, monkeypatch):
    monkeypatch.setattr(api, 'inspect_agent', lambda _: {'base_url': 'http://agent-a:8080', 'agent_id': 'pi-b', 'printers': [{'id': 'zebra-usb'}]})
    result = client.post('/v1/printers/register', json={'base_url': 'http://agent-a:8080', 'printer_id': 'zebra-usb', 'agent_id': 'pi-a', 'width_mm': 50, 'height_mm': 25, 'dpi': 203})
    assert result.status_code == 409
    assert client.get('/v1/printers/existing-id').json()['connection']['agent_id'] == 'pi-a'


def test_duplicate_legacy_aliases_are_flagged_without_merging(tmp_path, monkeypatch):
    registry = PrinterRegistry(tmp_path / 'db.sqlite3', tmp_path / 'absent.yml')
    registry.initialize()
    registry.create(printer('first', agent_id=None))
    registry.create(printer('second', agent_id=None, url='http://alias:8080'))
    monkeypatch.setattr(printer_discovery, 'discover_agent_urls', lambda: [])
    monkeypatch.setattr(printer_discovery, 'inspect_agent', lambda url: {'base_url': url, 'agent_id': 'pi-a', 'available': True, 'printers': [{'id': 'zebra-usb'}]})
    result = printer_discovery.discover_printers(registry)
    assert 'Multiple saved printers' in result['agents'][0]['printers'][0]['registration_conflict']
    assert len(registry.list()) == 2
    assert all('agent_id' not in p['connection'] for p in registry.export()['printers'])
