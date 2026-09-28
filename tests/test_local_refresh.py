"""Offline integration tests for the Windows publisher, using local Git repos."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'refresh_data_local.ps1'


@unittest.skipUnless(os.name == 'nt' and shutil.which('powershell.exe'), 'Windows PowerShell required')
class LocalRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cinema-refresh-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'checkout'
        self.remote = self.root / 'remote.git'
        self.state = self.root / 'state'
        self.repo.mkdir()
        self.git('init', '--bare', str(self.remote))
        self.git('init', '-b', 'main')
        self.git('config', 'user.name', 'Publisher test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'commit.gpgsign', 'false')
        (self.repo / 'dist').mkdir()
        for name in ('showtimes.json', 'poster_cache.json', 'cinema_health.json'):
            (self.repo / 'dist' / name).write_text('{}', encoding='utf-8')
        self.git('add', 'dist')
        self.git('commit', '-m', 'baseline')
        self.git('remote', 'add', 'origin', str(self.remote))
        self.git('push', 'origin', 'main')
        self.fake_python = self.root / 'python.cmd'
        self.fake_python.write_text(
            '@echo off\necho harmless native stderr 1>&2\n'
            '>dist\\showtimes.json echo {"test":true}\nexit /b 0\n', encoding='ascii'
        )

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, capture_output=True,
                              text=True, check=True).stdout.strip()

    def run_refresh(self):
        return subprocess.run([
            'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', str(SCRIPT), '-RepoRoot', str(self.repo),
            '-StateDir', str(self.state), '-PythonExecutable', str(self.fake_python),
            '-Force',
        ], capture_output=True, text=True, timeout=40)

    def assert_failed(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.state / 'last_success_date.txt').exists())
        self.assertTrue(list((self.state / 'logs').glob('*.log')))

    def test_success_accepts_stderr_and_publishes(self):
        result = self.run_refresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.state / 'last_success_date.txt').exists())
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'origin/main'))

    def test_build_failure_does_not_commit_or_mark_success(self):
        before = self.git('rev-parse', 'HEAD')
        self.fake_python.write_text('@echo off\necho build failed 1>&2\nexit /b 7\n')
        self.assert_failed(self.run_refresh())
        self.assertEqual(before, self.git('rev-parse', 'HEAD'))

    def test_development_branch_is_rejected(self):
        self.git('switch', '-c', 'codex/server-app')
        self.assert_failed(self.run_refresh())
        self.assertEqual((self.repo / 'dist/showtimes.json').read_text(), '{}')

    def test_staged_user_changes_are_rejected(self):
        (self.repo / 'user-work.txt').write_text('preserve me')
        self.git('add', 'user-work.txt')
        self.assert_failed(self.run_refresh())
        self.assertIn('user-work.txt', self.git('diff', '--cached', '--name-only'))

    def test_failed_push_can_retry_without_new_data(self):
        hook = self.remote / 'hooks/pre-receive'
        hook.write_text('#!/bin/sh\nexit 1\n', encoding='ascii')
        hook.chmod(0o755)
        self.assert_failed(self.run_refresh())
        committed = self.git('rev-parse', 'HEAD')
        self.assertNotEqual(committed, self.git('rev-parse', 'origin/main'))
        hook.unlink()
        result = self.run_refresh()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(committed, self.git('rev-parse', 'HEAD'))
        self.assertEqual(committed, self.git('rev-parse', 'origin/main'))
        self.assertTrue((self.state / 'last_success_date.txt').exists())


if __name__ == '__main__':
    unittest.main()
