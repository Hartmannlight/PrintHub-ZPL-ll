from __future__ import annotations

from io import BytesIO
import json
import re

from PIL import Image
import pytest

from zplgrid import api
from zplgrid.compiler import Compiler
from zplgrid.exceptions import TemplateValidationError
from zplgrid.macros import collect_template_placeholders
from zplgrid.model import LabelTarget
from zplgrid.parser import load_template
from zplgrid.printer_services import DeliveryReceipt, DeliveryState


def pair():
    return {
        'schema_version': 1,
        'layout': {'kind': 'leaf', 'elements': [{'type': 'text', 'text': '{from} -> {to}'}]},
        'labels': [{'name': 'A'}, {'name': 'B', 'bindings': {'from': 'to', 'to': 'from'}}],
    }


def test_partner_binding_is_simultaneous_and_does_not_mutate_inputs():
    values = {'from': 'SW-A', 'to': 'SRV-B'}
    result = Compiler().compile_with_diagnostics(load_template(pair()), target=LabelTarget(50, 25, 203), variables=values)
    assert result.zpl.count('^XA') == result.zpl.count('^XZ') == 2
    assert result.zpl.index('SW-A -> SRV-B') < result.zpl.index('SRV-B -> SW-A')
    assert values == {'from': 'SW-A', 'to': 'SRV-B'}
    assert not result.diagnostics


def test_independent_label_layouts_collect_and_resolve_shared_input_and_macros():
    doc = pair()
    doc['labels'] = [
        {'bindings': {'from': 'source', 'to': 'destination'}},
        {'layout': {'kind': 'leaf', 'elements': [{'type': 'text', 'text': 'DATE {date}'}]},
         'bindings': {'date': '_date_yyyy_mm_dd'}},
    ]
    assert collect_template_placeholders(load_template(doc)) == {'source', 'destination', '_date_yyyy_mm_dd'}
    result = api.render_zpl(api.RenderRequest(template=doc, variables={'source': 'A', 'destination': 'B'}, target=api.RenderTarget(width_mm=50, height_mm=25, dpi=203)))
    assert 'A -> B' in result.zpl
    assert re.search(r'\^FDDATE \d{4}-\d{2}-\d{2}', result.zpl)


@pytest.mark.parametrize('labels', [[], [{}] * 26, [{'bindings': {'invalid field': 'from'}}], [{'bindings': {'from': 'invalid field'}}]])
def test_invalid_label_sets_are_rejected(labels):
    doc = pair()
    doc['labels'] = labels
    with pytest.raises(TemplateValidationError):
        load_template(doc)


@pytest.mark.parametrize('mode,artifact_count', [('native', 1), ('raster', 2)])
def test_one_print_job_dispatches_all_labels_once_and_reuses_idempotency(tmp_path, monkeypatch, mode, artifact_count):
    monkeypatch.setenv('ZPLGRID_PRINT_JOBS_DIR', str(tmp_path / 'jobs'))
    printer = {
        'id': 'virtual', 'enabled': True,
        'accepted_mime_types': ['application/zpl', 'application/vnd.printhub.raster-page+json'],
        'media': {'revision': 'media-1', 'loaded': {'width_mm': 50, 'height_mm': 25, 'color': 'white'}},
        'alignment': {'dpi': 203},
    }
    deliveries = []
    rendered = []

    class Service:
        def deliver_job(self, artifacts, _printer, **options):
            deliveries.append((artifacts, options))
            return DeliveryReceipt(100, DeliveryState.TRANSPORT_ACCEPTED, 'pair-delivery', 'transport_accepted')

        def get_deliveries(self, ids):
            return {item: DeliveryReceipt(100, DeliveryState.TRANSPORT_ACCEPTED, item, 'transport_accepted') for item in ids}

    def render(zpl, **options):
        rendered.append(zpl)
        assert options['index'] == 0 and zpl.count('^XA') == 1
        stream = BytesIO()
        Image.new('RGB', (400, 200), 'white').save(stream, format='PNG')
        return stream.getvalue()

    monkeypatch.setattr(api, '_get_printer', lambda _id: printer)
    monkeypatch.setattr(api, '_printer_services', lambda: Service())
    monkeypatch.setattr(api, 'render_labelary_png_bytes', render)
    request = api.PrintJobCreateRequest(printer_id='virtual', template=pair(), variables={'from': 'SW-A', 'to': 'SRV-B'}, output_mode=mode, idempotency_key='pair-once')
    first = api.create_print_job(request)
    second = api.create_print_job(request)
    assert first.id == second.id
    assert first.status == 'queued'
    assert second.status == 'transport_accepted'
    assert first.page_count == 2
    assert len(deliveries) == 1
    artifacts, options = deliveries[0]
    assert len(artifacts) == artifact_count
    assert options['copies'] == 1
    if mode == 'native':
        assert artifacts[0].payload.count(b'^XA') == 2
        assert b'SW-A -> SRV-B' in artifacts[0].payload
        assert b'SRV-B -> SW-A' in artifacts[0].payload
    else:
        assert len(rendered) == 2
        assert 'SW-A -> SRV-B' in rendered[0] and 'SRV-B -> SW-A' in rendered[1]
        assert all(json.loads(item.payload)['copies'] == 1 for item in artifacts)


def test_shrink_without_soft_wrap_preserves_manual_lines_and_reduces_font():
    line = 'Long server and port information with spaces'
    template = load_template({'schema_version': 1, 'layout': {'kind': 'leaf', 'elements': [{
        'type': 'text', 'text': '{value}', 'font_height_mm': 5,
        'wrap': 'none', 'fit': 'shrink_to_fit', 'align_h': 'center', 'align_v': 'center',
    }]}})
    result = Compiler().compile_with_diagnostics(template, target=LabelTarget(35, 20, 203), variables={'value': line + '\nBOND 11'})
    assert [field.strip('\n').removesuffix('\\&') for field in re.findall(r'\^FD(.*?)\^FS', result.zpl, re.DOTALL)] == [line, 'BOND 11']
    sizes = re.findall(r'\^A0N,(\d+),(\d+)', result.zpl)
    assert len(sizes) == 2 and sizes[0] == sizes[1]
    assert int(sizes[0][0]) < 40
    assert not result.diagnostics
