import json
from pathlib import Path

from zplgrid import LabelTarget, compile_zpl


def main() -> None:
    template = json.loads(Path('qr_left_text_right.template.json').read_text(encoding='utf-8'))

    zpl = compile_zpl(
        template,
        target=LabelTarget(width_mm=74.0, height_mm=26.0, dpi=203),
        variables={
            'asset_id': 'A-001-2025',
            'title': 'Cable Box 1',
            'subtitle': 'USB-C / PD 100W',
        },
        debug=True,
    )

    Path('out.zpl').write_text(zpl, encoding='utf-8')
    print(zpl)


if __name__ == '__main__':
    main()
