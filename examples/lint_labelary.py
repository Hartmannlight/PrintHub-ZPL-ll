from __future__ import annotations

import argparse
import json
from pathlib import Path

from zplgrid import LabelTarget, compile_zpl
from zplgrid.labelary import lint_labelary_zpl


DEFAULT_TEMPLATE = {
    "schema_version": 1,
    "name": "qr_top_right",
    "defaults": {
        "leaf_padding_mm": [0, 0, 0, 0],
        "code2d": {"quiet_zone_mm": 1},
        "render": {"missing_variables": "error", "emit_ci28": True},
    },
    "layout": {
        "kind": "leaf",
        "elements": [
            {
                "type": "qr",
                "data": "das sind meine qr code daten",
                "quiet_zone_mm": 0,
                "align_v": "top",
                "align_h": "right",
            }
        ],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Compile template and lint via Labelary.")
    parser.add_argument("template", nargs="?", help="Path to template JSON file.")
    parser.add_argument("--width-mm", type=float, default=74.0)
    parser.add_argument("--height-mm", type=float, default=26.0)
    parser.add_argument("--dpi", type=int, default=203)
    parser.add_argument("--no-compact", action="store_true", help="Send ZPL with newlines to Labelary.")
    args = parser.parse_args()

    if args.template:
        template_path = Path(args.template)
        template = json.loads(template_path.read_text(encoding="utf-8"))
    else:
        template = DEFAULT_TEMPLATE

    target = LabelTarget(width_mm=args.width_mm, height_mm=args.height_mm, dpi=args.dpi)
    zpl = compile_zpl(template, target=target, variables={}, debug=False)
    zpl_for_lint = zpl

    warnings = lint_labelary_zpl(
        zpl_for_lint,
        dpmm=int(round(args.dpi / 25.4)),
        label_width_in=args.width_mm / 25.4,
        label_height_in=args.height_mm / 25.4,
        compact=not args.no_compact,
    )

    print("ZPL:")
    print(zpl)
    print("Warnings:")
    if not warnings:
        print("  (none)")
        return 0
    for warning in warnings:
        cmd = warning.command or "-"
        param = str(warning.param_index) if warning.param_index is not None else "-"
        print(
            f"- idx={warning.byte_index} size={warning.byte_size} cmd={cmd} param={param}: {warning.message}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
