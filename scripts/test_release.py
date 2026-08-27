"""Release boundary tests: no network, credentials, registry writes or deployments."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import release
import security_gate


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, self.cwd)
        self.env = patch.dict(os.environ, {
            'IMAGE': 'ghcr.io/example/test', 'GITHUB_SHA': 'a' * 40,
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
            'GITHUB_REF': 'refs/heads/main', 'DIGEST': 'sha256:' + 'b' * 64,
            'GITHUB_OUTPUT': 'outputs', 'GITHUB_STEP_SUMMARY': 'summary',
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_existing_immutable_reference_is_rejected(self):
        with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, 'overwrite'):
                release.absent('existing')

    def test_registry_auth_failure_is_not_treated_as_absent(self):
        with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'unauthorized')):
            with self.assertRaisesRegex(RuntimeError, 'Cannot establish'):
                release.absent('unknown')

    def test_registry_missing_manifest_is_accepted(self):
        with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'manifest unknown')):
            release.absent('new')

    def test_dependency_branches_cannot_publish(self):
        with patch.dict(os.environ, {'GITHUB_REF': 'refs/heads/renovate/example'}):
            with self.assertRaisesRegex(RuntimeError, 'restricted'):
                release.main()

    def test_old_main_build_does_not_move_latest(self):
        with patch('sys.argv', ['release.py', 'promote']), patch.object(release, 'run', return_value='c' * 40 + '\trefs/heads/main') as run:
            with contextlib.redirect_stdout(io.StringIO()):
                release.main()
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('latest', Path('summary').read_text())

    def test_current_main_promotes_the_validated_digest(self):
        with patch('sys.argv', ['release.py', 'promote']), patch.object(release, 'run', side_effect=['a' * 40 + '\trefs/heads/main', '']) as run:
            release.main()
            self.assertEqual(run.call_args.args, ('docker', 'buildx', 'imagetools', 'create', '-t', 'ghcr.io/example/test:latest', 'ghcr.io/example/test@sha256:' + 'b' * 64))

    def test_partial_platform_set_cannot_publish_an_index(self):
        Path('metadata').mkdir()
        Path('metadata/amd64.json').write_text(json.dumps({'arch': 'amd64', 'reference': 'unused'}))
        with patch('sys.argv', ['release.py', 'merge']), patch.object(release, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Both platform'):
                release.main()
            run.assert_not_called()

    def test_unpatched_findings_remain_visible(self):
        blocked, unpatched = security_gate.findings({'Results': [{'Vulnerabilities': [
            {'VulnerabilityID': 'test-fixed', 'PkgName': 'example', 'Severity': 'HIGH', 'FixedVersion': '2'},
            {'VulnerabilityID': 'test-unpatched', 'PkgName': 'example', 'Severity': 'CRITICAL'},
        ]}]})
        self.assertEqual(blocked, [('test-fixed', 'example')])
        self.assertEqual(unpatched, [('test-unpatched', 'example')])

    def test_empty_scanner_output_fails_closed(self):
        with self.assertRaises(ValueError):
            security_gate.findings({})


if __name__ == '__main__':
    unittest.main()
