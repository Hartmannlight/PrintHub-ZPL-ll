import pytest

from zplgrid.compiler import compile_zpl
from zplgrid.exceptions import CompilationError
from zplgrid.model import LabelTarget


def _base_template(element):
    return {
        'schema_version': 1,
        'name': 'code2d_image_mode',
        'defaults': {
            'leaf_padding_mm': [0, 0, 0, 0],
        },
        'layout': {
            'kind': 'leaf',
            'elements': [element],
        },
    }


def test_qr_image_mode_requires_segno():
    template = _base_template(
        {
            'type': 'qr',
            'data': 'HELLO',
            'render_mode': 'image',
            'magnification': 2,
        }
    )
    with pytest.raises(CompilationError, match='segno'):
        compile_zpl(template, target=LabelTarget(width_mm=20.0, height_mm=20.0, dpi=203))


def test_datamatrix_image_mode_requires_pylibdmtx():
    template = _base_template(
        {
            'type': 'datamatrix',
            'data': 'HELLO',
            'render_mode': 'image',
            'module_size_mm': 0.5,
        }
    )
    with pytest.raises(CompilationError, match='pylibdmtx'):
        compile_zpl(template, target=LabelTarget(width_mm=20.0, height_mm=20.0, dpi=203))
