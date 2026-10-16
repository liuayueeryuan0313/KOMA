import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen

from app_version import VERSION,read_build_date,write_build_info
from core import Store
from server import CalendarServer
from sync import SyncManager


class BuildInfoTests(unittest.TestCase):
    def test_missing_invalid_or_other_version_metadata_is_not_a_build_date(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'build-info.json'
            self.assertIsNone(read_build_date(path))
            path.write_text('broken JSON');self.assertIsNone(read_build_date(path))
            for info in [[],{}, {'version':'0.3.0','build_date':'2026-10-16T10:00:00Z'}, {'version':VERSION,'build_date':'2026-10-16'}, {'version':VERSION,'build_date':'2026-10-16T10:00:00'}, {'version':VERSION,'build_date':'not a date'}]:
                with self.subTest(info=info):
                    path.write_text(json.dumps(info));self.assertIsNone(read_build_date(path))

    def test_build_stamp_normalizes_utc_and_does_not_change_when_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'build-info.json'
            result=write_build_info(path,'2026-10-16T18:00:00+08:00')
            self.assertEqual(result,{'version':VERSION,'build_date':'2026-10-16T10:00:00Z'})
            before=path.read_bytes()
            self.assertEqual(read_build_date(path),'2026-10-16T10:00:00Z')
            self.assertEqual(path.read_bytes(),before)
            with patch.dict('os.environ',{'KOMA_BUILD_DATE':'2026-10-17T01:02:03Z'}):write_build_info(path)
            self.assertEqual(read_build_date(path),'2026-10-17T01:02:03Z')

    def test_docker_version_matches_application_and_stamp_is_build_time_only(self):
        root=Path(__file__).resolve().parents[1]
        docker=(root/'Dockerfile').read_text()
        self.assertIn(f'org.opencontainers.image.version="{VERSION}"',docker)
        self.assertIn('ARG KOMA_BUILD_DATE',docker)
        self.assertIn('RUN python -c "from app_version import write_build_info; write_build_info()"',docker)
        for name in ['.gitignore','.dockerignore']:self.assertIn('build-info.json',(root/name).read_text())

    def test_login_bootstrap_and_health_share_version_and_stored_build_date(self):
        with tempfile.TemporaryDirectory() as directory,patch('server.BUILD_DATE','2026-10-16T10:00:00Z'):
            store=Store(directory);manager=SyncManager(store)
            server=CalendarServer(('127.0.0.1',0),store,manager)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                for path in ['/api/bootstrap','/healthz']:
                    with urlopen(f'http://127.0.0.1:{server.server_port}'+path) as response:payload=json.load(response)
                    self.assertEqual(payload['version'],VERSION)
                    self.assertEqual(payload['build_date'],'2026-10-16T10:00:00Z')
            finally:
                server.shutdown();server.server_close();manager.close();thread.join(timeout=3)


if __name__=='__main__':unittest.main()
