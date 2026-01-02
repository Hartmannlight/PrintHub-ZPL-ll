import base64
import io

from PIL import Image

from zplgrid.compiler import compile_zpl
from zplgrid.model import LabelTarget


def test_image_base64_inline_emits_gfa():
    img = Image.new('RGB', (8, 8), color='black')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64 = base64.b64encode(buf.getvalue()).decode('ascii')

    template = {
        'schema_version': 1,
        'name': 'image_base64',
        'defaults': {
            'leaf_padding_mm': [0, 0, 0, 0],
        },
        'layout': {
            'kind': 'leaf',
            'elements': [
                {
                    'type': 'image',
                    'source': {'kind': 'base64', 'data': b64},
                    'fit': 'none',
                    'align_h': 'left',
                    'align_v': 'top',
                    'dither': 'none',
                    'threshold': 128,
                }
            ],
        },
    }

    zpl = compile_zpl(template, target=LabelTarget(width_mm=10.0, height_mm=10.0, dpi=203))
    assert '^GFA,8,8,1,FFFFFFFFFFFFFFFF' in zpl

