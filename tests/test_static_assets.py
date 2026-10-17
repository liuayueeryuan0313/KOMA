import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core import Store
from server import CalendarServer
from sync import SyncManager
from test_service import FakeBridge


class StaticAssetTests(unittest.TestCase):
    def test_assets_revalidate_without_caching_private_responses_or_stale_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web = root / 'web'
            web.mkdir()
            for name, content in [('index.html', '<html></html>'), ('style.css', 'body{color:red}'),
                                  ('app.js', 'void 0;'), ('mascot.svg', '<svg/>')]:
                (web / name).write_text(content)
            store = Store(root / 'data')
            manager = SyncManager(store, FakeBridge())
            server = CalendarServer(('127.0.0.1', 0), store, manager)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'

            def request(path, method='GET', headers=None):
                return urlopen(Request(base + path, method=method, headers=headers or {}), timeout=5)

            try:
                with patch('server.ROOT', root):
                    for path in ['/style.css', '/app.js', '/mascot.svg']:
                        with request(path) as response:
                            content = response.read()
                            etag = response.headers['ETag']
                            self.assertEqual(response.headers['Cache-Control'], 'public, max-age=0, must-revalidate')
                        for condition in [etag, 'W/' + etag, '"other", ' + etag, '*']:
                            with self.assertRaises(HTTPError) as unchanged:
                                request(path, headers={'If-None-Match': condition})
                            self.assertEqual(unchanged.exception.code, 304)
                            self.assertEqual(unchanged.exception.read(), b'')
                            self.assertEqual(unchanged.exception.headers['Content-Length'], str(len(content)))
                        with request(path, method='HEAD') as response:
                            self.assertEqual(response.read(), b'')
                            self.assertEqual(response.headers['ETag'], etag)
                            self.assertEqual(response.headers['Content-Length'], str(len(content)))
                    with request('/style.css') as response:
                        old_etag = response.headers['ETag']
                    (web / 'style.css').write_text('body{color:blue}')
                    with request('/style.css', headers={'If-None-Match': old_etag}) as response:
                        self.assertEqual(response.status, 200)
                        self.assertNotEqual(response.headers['ETag'], old_etag)
                        self.assertEqual(response.read(), b'body{color:blue}')
                    for path in ['/', '/api/bootstrap']:
                        with request(path) as response:
                            self.assertEqual(response.headers['Cache-Control'], 'no-store')
                            self.assertIsNone(response.headers['ETag'])
                    with request('/api/bootstrap') as response:
                        self.assertTrue(json.load(response)['setup_required'])
            finally:
                server.shutdown()
                server.server_close()
                manager.close()
                thread.join(timeout=3)
