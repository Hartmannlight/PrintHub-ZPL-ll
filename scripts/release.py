"""Publish only the tested archives. Never overwrite immutable release tags."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def output(key, value):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write(f'{key}={value}\n')

def absent(reference):
    result = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', reference], capture_output=True, text=True)
    if result.returncode == 0:
        raise RuntimeError(f'Refusing to overwrite immutable reference {reference}')
    message = (result.stderr + result.stdout).lower()
    if not any(term in message for term in ('not found', 'manifest unknown', 'no such manifest')):
        raise RuntimeError(f'Cannot establish whether {reference} exists: {result.stderr}')

def main():
    image = os.environ['IMAGE']
    sha = os.environ['GITHUB_SHA']
    build = f'sha-{sha}-r{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
    ref = os.environ['GITHUB_REF']
    if ref != 'refs/heads/main' and not re.fullmatch(r'refs/tags/v\d+\.\d+\.\d+', ref):
        raise RuntimeError('Publication is restricted to main and exact release tags')
    version = ref.removeprefix('refs/tags/') if ref.startswith('refs/tags/') else None
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise RuntimeError('Unexpected source SHA')
    if version and not re.fullmatch(r'v\d+\.\d+\.\d+', version):
        raise RuntimeError('Only exact vMAJOR.MINOR.PATCH releases are supported')
    if sys.argv[1] == 'platform':
        arch = os.environ['ARCH']
        if arch not in ('amd64', 'arm64'):
            raise RuntimeError('Unexpected platform')
        tag = f'{image}:{build}-{arch}'
        absent(tag)
        run('docker', 'load', '-i', 'candidate/image.tar')
        run('docker', 'tag', 'candidate:gate', tag)
        run('docker', 'push', tag)
        digest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', tag, '--format', '{{json .Manifest}}'))['digest']
        Path('metadata').mkdir(exist_ok=True)
        Path(f'metadata/{arch}.json').write_text(json.dumps({'arch': arch, 'reference': image + '@' + digest}))
        output('digest', digest)
        output('image', image)
    elif sys.argv[1] == 'merge':
        entries = [json.loads(path.read_text()) for path in sorted(Path('metadata').glob('*.json'))]
        if {entry['arch'] for entry in entries} != {'amd64', 'arm64'} or len(entries) != 2:
            raise RuntimeError('Both platform images are required before publication')
        references = [entry['reference'] for entry in entries]
        if any(not re.fullmatch(re.escape(image) + r'@sha256:[a-f0-9]{64}', value) for value in references):
            raise RuntimeError('Invalid platform reference')
        immutable = image + ':' + build
        absent(immutable)
        if version:
            # Version releases must originate from the supported main history.
            run('git', 'fetch', 'origin', 'main')
            subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'FETCH_HEAD'], check=True)
            absent(image + ':' + version)
        run('docker', 'buildx', 'imagetools', 'create', '-t', immutable, *references)
        manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', immutable, '--format', '{{json .Manifest}}'))
        platforms = {(m.get('platform', {}).get('os'), m.get('platform', {}).get('architecture')) for m in manifest['manifests']}
        if not {('linux', 'amd64'), ('linux', 'arm64')} <= platforms:
            raise RuntimeError('Published index is missing a supported platform')
        output('digest', manifest['digest'])
        output('immutable', immutable)
        output('image', image)
        Path('release-digest.txt').write_text(image + '@' + manifest['digest'] + '\n')
    elif sys.argv[1] == 'promote':
        digest = os.environ['DIGEST']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
            raise RuntimeError('Invalid validated image digest')
        target = image + '@' + digest
        tags = []
        if version:
            absent(image + ':' + version)
            tags.append(image + ':' + version)
        elif ref == 'refs/heads/main':
            latest_main = run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0]
            if latest_main == sha:
                tags.append(image + ':latest')
            else:
                print('Newer main exists: immutable artifact retained; latest not moved')
        for tag in tags:
            run('docker', 'buildx', 'imagetools', 'create', '-t', tag, target)
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(f'## Validated container release\nSource: `{sha}`\n\nImmutable: `{image}:{build}`\n\nDigest: `{target}`\n\nPromoted: {tags}\n\nBoth native platform smoke tests and scan gates passed. Platform SBOMs and provenance are attached. No deployment performed.\n')
    else:
        raise RuntimeError('Unknown release operation')

if __name__ == '__main__':
    main()
