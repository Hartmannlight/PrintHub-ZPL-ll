import base64
import io

from PIL import Image

from zplgrid.compiler import compile_zpl
from zplgrid.macros import collect_template_placeholders
from zplgrid.model import LabelTarget
from zplgrid.parser import load_template


def _black_png_base64() -> str:
    image = Image.new('RGB', (1, 1), color='black')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('ascii')


def _background(data: str) -> dict:
    return {
        'source': {'kind': 'base64', 'data': data},
        'fit': 'stretch',
        'threshold': 128,
        'dither': 'none',
    }


def test_background_is_supported_on_root_split_and_leaf_and_precedes_content():
    image_data = _black_png_base64()
    template = {
        'schema_version': 1,
        'name': 'node_backgrounds',
        'defaults': {'leaf_padding_mm': [0, 0, 0, 0]},
        'layout': {
            'kind': 'split',
            'direction': 'v',
            'ratio': 0.5,
            'background': _background(image_data),
            'children': [
                {
                    'kind': 'leaf',
                    'background': _background(image_data),
                    'elements': [{'type': 'text', 'text': 'Hello'}],
                },
                {
                    'kind': 'leaf',
                    'elements': [{'type': 'qr', 'data': 'world'}],
                },
            ],
        },
    }

    parsed = load_template(template)
    assert parsed.layout.background is not None
    assert parsed.layout.children[0].background is not None
    assert parsed.layout.children[1].background is None

    zpl = compile_zpl(template, target=LabelTarget(width_mm=20.0, height_mm=10.0, dpi=203))
    assert zpl.count('^GFA') == 2
    assert zpl.rfind('^GFA') < zpl.index('^FDHello')


def test_background_uses_image_defaults():
    image_data = _black_png_base64()
    parsed = load_template({
        'schema_version': 1,
        'defaults': {'image': {'fit': 'cover', 'invert': True}},
        'layout': {
            'kind': 'leaf',
            'background': {'source': {'kind': 'base64', 'data': image_data}},
            'elements': [{'type': 'text', 'text': 'foreground'}],
        },
    })
    assert parsed.layout.background is not None
    assert parsed.layout.background.fit == 'cover'
    assert parsed.layout.background.invert is True


def test_background_source_placeholders_are_collected():
    parsed = load_template({
        'schema_version': 1,
        'layout': {
            'kind': 'leaf',
            'background': {'source': {'kind': 'url', 'data': 'https://example.test/{asset_id}.png'}},
            'elements': [{'type': 'text', 'text': '{caption}'}],
        },
    })
    assert collect_template_placeholders(parsed) == {'asset_id', 'caption'}
