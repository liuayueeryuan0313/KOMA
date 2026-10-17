import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import sys
import tempfile
import unittest
from urllib.request import urlopen

from koma.app_version import BUILD_INFO_PATH, VERSION
from koma.core import ROOT
from koma.school_profiles import DEFAULTS


class PackageLayoutTests(unittest.TestCase):
    def test_runtime_resources_keep_their_existing_project_root(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(ROOT, root)
        self.assertEqual(BUILD_INFO_PATH, root / 'build-info.json')
        self.assertEqual(DEFAULTS, json.loads((root / 'adapters/school-defaults.json').read_text()))
        for name in ['index.html', 'app.js', 'style.css']:
            self.assertTrue((root / 'web' / name).is_file())

    def test_both_entrypoints_serve_with_isolated_data_and_correct_static_paths(self):
        for module in [False, True]:
            with self.subTest(module=module), tempfile.TemporaryDirectory() as directory:
                command = [sys.executable, '-m', 'koma'] if module else [sys.executable, str(ROOT / 'server.py')]
                environment = dict(os.environ, DATA_DIR=directory, HOST='127.0.0.1', PORT='0',
                                   PUBLIC_URL='', ADMIN_USERNAME='', ADMIN_PASSWORD='', PYTHONDONTWRITEBYTECODE='1')
                process = subprocess.Popen(command, cwd=ROOT if module else directory,
                                           env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True)
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(process.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=10), 'Service startup timed out')
                    line = process.stdout.readline()
                    match = re.search(r'http://127\.0\.0\.1:\d+', line)
                    self.assertIsNotNone(match, line)
                    base = match.group()
                    with urlopen(base + '/healthz', timeout=5) as response:
                        self.assertEqual(json.load(response)['version'], VERSION)
                    with urlopen(base + '/api/bootstrap', timeout=5) as response:
                        self.assertTrue(json.load(response)['setup_required'])
                    with urlopen(base + '/', timeout=5) as response:
                        self.assertIn('课间 · KOMA', response.read().decode())
                    with urlopen(base + '/style.css', timeout=5) as response:
                        self.assertIn(b'.sidebar', response.read())
                    self.assertTrue((Path(directory) / 'komama.sqlite3').is_file())
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                    process.stdout.close()
