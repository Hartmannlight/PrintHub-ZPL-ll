from __future__ import annotations

import os
from pathlib import Path


APP_UID = 10001
APP_GID = 10001
DATA_ROOT = Path('/data')


def prepare_data_directory(root: Path = DATA_ROOT) -> None:
    """Make old named volumes writable, then leave root before serving."""
    if os.geteuid() != 0:
        return
    for directory, subdirectories, files in os.walk(root):
        os.chown(directory, APP_UID, APP_GID)
        for name in subdirectories:
            os.chown(Path(directory) / name, APP_UID, APP_GID)
        for name in files:
            os.chown(Path(directory) / name, APP_UID, APP_GID)


def main() -> None:
    prepare_data_directory()
    if os.geteuid() == 0:
        os.setgroups([])
        os.setgid(APP_GID)
        os.setuid(APP_UID)
    os.execvp(
        'uvicorn',
        ['uvicorn', 'zplgrid.api:app', '--host', '0.0.0.0', '--port', '8000'],
    )


if __name__ == '__main__':
    main()
