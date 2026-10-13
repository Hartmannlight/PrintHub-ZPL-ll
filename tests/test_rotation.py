from __future__ import annotations

import json
from pathlib import Path
import re

from PIL import Image
import pytest

from zplgrid.compiler import Compiler
from zplgrid.cable_flag import prepare_cable_flag
from zplgrid.exceptions import CompilationError, TemplateValidationError
from zplgrid.layout import compute_layout
from zplgrid.model import LabelTarget, Rect
from zplgrid.parser import load_template
from zplgrid.rotation import Transform, TransformedZplBuilder
from zplgrid.zpl import ZplBuilder


@pytest.mark.parametrize('angle,orientation', [(0, 'N'), (90, 'R'), (180, 'I'), (-90, 'B'), (270, 'B')])
def test_text_rotation_keeps_asymmetric_padding_and_wrapping_in_local_axes(angle, orientation):
    template = load_template({'schema_version': 1, 'layout': {
        'kind': 'leaf', 'rotation_deg': angle, 'padding_mm': [1, 2, 3, 4],
        'elements': [{'type': 'text', 'text': 'ALPHA\nBETA', 'font_height_mm': 3,
                      'wrap': 'word', 'fit': 'shrink_to_fit', 'align_h': 'center'}],
    }})
    layout = compute_layout(template.layout, width_dots=400, height_dots=240, dpi=254)
    leaf = layout.leaves[0]
    assert leaf.rect == Rect(0, 0, 400, 240)
    assert leaf.content_rect.w == (240 if angle in (90, -90, 270) else 400) - 60
    result = Compiler().compile_with_diagnostics(template, target=LabelTarget(40, 24, 254), variables={})
    assert result.zpl.count(f'^A0{orientation},') == 2
    assert not result.diagnostics
    for x, y in re.findall(r'\^FO(\d+),(\d+)', result.zpl):
        assert 0 <= int(x) < 400 and 0 <= int(y) < 240


def test_nested_rotations_compose_and_dividers_follow_the_area():
    template = load_template({'schema_version': 1, 'layout': {
        'kind': 'split', 'rotation_deg': 90, 'direction': 'h', 'ratio': .25,
        'gutter_mm': 2, 'divider': {'visible': True, 'thickness_mm': 1}, 'children': [
            {'kind': 'leaf', 'alias': 'a', 'rotation_deg': -90, 'elements': [{'type': 'text', 'text': 'A'}]},
            {'kind': 'leaf', 'alias': 'b', 'elements': [{'type': 'text', 'text': 'B'}]},
        ],
    }})
    layout = compute_layout(template.layout, width_dots=400, height_dots=240, dpi=254)
    assert layout.leaves[0].rect == Rect(305, 0, 95, 240)
    assert layout.leaves[0].transform.orientation == 'N'
    assert layout.leaves[1].rect == Rect(0, 0, 285, 240)
    assert layout.leaves[1].transform.orientation == 'R'
    assert layout.dividers[0].rect == Rect(290, 0, 10, 240)
    assert layout.alias_to_id == {'a': 'r/0', 'b': 'r/1'}


@pytest.mark.parametrize('angle', [90, 180, -90])
def test_bitmap_rotation_preserves_nonbyte_width_and_black_pixel_locations(angle):
    image = Image.new('1', (3, 2), 0)
    image.putpixel((0, 0), 1)
    image.putpixel((2, 1), 1)
    raw = image.tobytes()
    transform, _ = Transform().child(Rect(10, 20, 2 if angle != 180 else 3, 3 if angle != 180 else 2), angle)
    builder = ZplBuilder()
    rotated = TransformedZplBuilder(builder, transform)
    rotated.field_origin(0, 0)
    rotated.graphic_field(total_bytes=len(raw), bytes_per_row=1, data=raw.hex(), width=3)
    result = builder.build()
    count, stride, data = re.search(r'\^GFA,(\d+),\d+,(\d+),([A-F0-9]+)', result).groups()
    actual = Image.frombytes('1', (int(stride)*8, int(count)//int(stride)), bytes.fromhex(data))
    expected = image.transpose({90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, -90: Image.Transpose.ROTATE_90}[angle])
    assert actual.crop((0, 0, *expected.size)).tobytes() == expected.tobytes()
    assert '^FO10,20' in result


def test_nonquarter_turn_is_rejected_by_public_schema():
    with pytest.raises(TemplateValidationError):
        load_template({'schema_version': 1, 'layout': {'kind': 'leaf', 'rotation_deg': 45, 'elements': [{'type': 'text', 'text': 'A'}]}})


def test_bundled_cable_flag_reserves_full_circumference_and_has_both_endpoints_on_both_faces():
    directory = Path(__file__).parents[1] / 'templates' / 'kabel-faehnchen-75x50'
    raw = json.loads((directory / 'template.json').read_text())
    variables = json.loads((directory / 'sample_data.json').read_text())
    result = Compiler().compile_with_diagnostics(load_template(raw), target=LabelTarget(75, 50, 203), variables=variables)
    assert not result.diagnostics
    assert result.zpl.count('VON: SW321 [32]') == 2
    assert result.zpl.count('ZU: #543 [1]') == 2
    assert result.zpl.count('VON: #543 [1]') == 2
    assert result.zpl.count('ZU: SW321 [32]') == 2
    assert result.zpl.count('B11') == 4
    assert result.zpl.count('^XA') == 2
    assert result.zpl.count('^GB2,400,2') == 2
    assert '^A0R,' in result.zpl and '^A0B,' in result.zpl
    # Increasing diameter shrinks the two faces while preserving the short edge.
    raw['extensions']['cable_flag']['diameter_mm'] = 10
    second = Compiler().compile_with_diagnostics(load_template(raw), target=LabelTarget(75, 50, 203), variables=variables)
    assert not second.diagnostics
    assert second.zpl != result.zpl
    raw['extensions']['cable_flag']['diameter_mm'] = 30
    with pytest.raises(CompilationError, match='less than 6 mm'):
        load_template(raw).compile(target=LabelTarget(75, 50, 203), variables=variables)


@pytest.mark.parametrize('angle', [0, 90, 180, -90])
def test_cable_padding_stays_next_to_cable_when_face_rotation_changes(angle):
    directory = Path(__file__).parents[1] / 'templates' / 'kabel-faehnchen-75x50'
    raw = json.loads((directory / 'template.json').read_text())
    raw['layout']['children'][0]['rotation_deg'] = angle
    node = prepare_cable_flag(load_template(raw), LabelTarget(75, 50, 254))
    layout = compute_layout(node, width_dots=750, height_dots=500, dpi=254)
    front = layout.leaves[0]
    assert front.transform.orientation == {0: 'N', 90: 'R', 180: 'I', -90: 'B'}[angle]
    content = front.transform.bounds(front.content_rect)
    assert front.rect.x + front.rect.w - content.x - content.w == 20
