import argparse
import json
from pathlib import Path

from zplgrid.api import app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the PrintHub OpenAPI schema to disk.")
    parser.add_argument(
        "output",
        nargs="?",
        default="openapi.json",
        help="Output path for the generated OpenAPI document.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    openapi = app.openapi()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(openapi, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
