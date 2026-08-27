"""Bounded smoke test against the exact candidate image; never use real printers."""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SERVICE = 'hub'
PORT = 8000
PATH = '/health'

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def main():
    image = sys.argv[1]
    user = run('docker', 'image', 'inspect', image, '--format', '{{.Config.User}}')
    if not user or user.split(':')[0] in ('root', '0'):
        raise RuntimeError('Runtime image must run as a non-root user')
    args = ['docker', 'run', '-d', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
            '-p', f'127.0.0.1::{PORT}']
    if SERVICE == 'hub':
        args += ['-e', 'ZPLGRID_DISCOVERY_INTERVAL_SECONDS=0']
    container = run(*args, image)
    Path('artifacts').mkdir(exist_ok=True)
    try:
        binding = run('docker', 'port', container, f'{PORT}/tcp').splitlines()[0]
        base = 'http://' + binding
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(base + PATH, timeout=3) as response:
                    data = response.read()
                    if response.status != 200:
                        raise RuntimeError('Unhealthy response')
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        if SERVICE == 'studio':
            assert b'<html' in data.lower()
            with urllib.request.urlopen(base + '/config.js', timeout=3) as response:
                assert b'/api' in response.read()
        elif SERVICE == 'hub':
            assert json.loads(data)['status'] == 'ok'
            with urllib.request.urlopen(base + '/v1/printers', timeout=3) as response:
                assert isinstance(json.load(response)['printers'], list)
        else:
            assert json.loads(data)['status'] == 'ok'
            with urllib.request.urlopen(base + '/api/settings', timeout=3) as response:
                assert json.load(response)['dpmm'] > 0
        print(f'{SERVICE}: runtime health and API smoke passed')
    finally:
        logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
        Path('artifacts/container.log').write_text(logs.stdout + logs.stderr)
        subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)

if __name__ == '__main__':
    main()
