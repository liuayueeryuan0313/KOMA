import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError,URLError
from urllib.request import urlopen
from unittest.mock import Mock

from koma.app_version import VERSION
from koma.updates import UpdateChecker,is_newer,LATEST_API,RELEASES_URL


class Reply:
    def __init__(self,payload):self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,limit):return self.payload[:limit]


def release(tag=None,**fields):
    tag=tag or 'v'+VERSION
    return Reply(json.dumps({'tag_name':tag,'draft':False,'prerelease':False,**fields}).encode())


class UpdateTests(unittest.TestCase):
    def test_semver_numeric_prerelease_and_build_comparison(self):
        for latest,current,expected in [('v0.10.0','0.9.9',True),('v1.0.0','0.99.9',True),('v0.3.0','0.3.0',False),('v0.2.9','0.3.0',False),('1.0.0','1.0.0-rc.1',True),('1.0.0-rc.10','1.0.0-rc.2',True),('1.0.0-beta','1.0.0-1',True),('1.0.0+new','1.0.0+old',False)]:
            with self.subTest(latest=latest,current=current):self.assertEqual(is_newer(latest,current),expected)
        for invalid in ('latest','1.2','01.2.3','1.2.3-01','<script>'):
            with self.assertRaises(ValueError):is_newer(invalid,'0.3.0')

    def test_latest_status_and_new_release_status_use_fixed_public_repo(self):
        opener=Mock(return_value=release())
        checker=UpdateChecker(opener=opener)
        self.assertEqual(checker.check()['status'],'current')
        request=opener.call_args.args[0]
        self.assertEqual(request.full_url,LATEST_API)
        self.assertEqual(opener.call_args.kwargs['timeout'],8)
        self.assertNotIn('Authorization',request.headers)
        result=UpdateChecker(opener=Mock(return_value=release('v0.5.0',html_url='https://evil.example/'))).check()
        self.assertEqual(result['status'],'available')
        self.assertEqual(result['release_url'],RELEASES_URL+'/tag/v0.5.0')

    def test_cache_avoids_repeated_github_requests_and_expires(self):
        tick=[0];opener=Mock(side_effect=[release(),release('v0.5.0')])
        checker=UpdateChecker(opener=opener,clock=lambda:tick[0])
        self.assertFalse(checker.check()['cached'])
        self.assertTrue(checker.check()['cached'])
        self.assertEqual(opener.call_count,1)
        tick[0]=301
        self.assertEqual(checker.check()['status'],'available')
        self.assertEqual(opener.call_count,2)

    def test_missing_release_rate_limit_and_network_failure_never_report_current(self):
        for exception,status in [(HTTPError(LATEST_API,404,'missing',{},None),'unavailable'),(HTTPError(LATEST_API,403,'limited',{},None),'error'),(HTTPError(LATEST_API,429,'limited',{},None),'error'),(URLError('network'),'error'),(TimeoutError(),'error')]:
            with self.subTest(exception=type(exception).__name__):
                result=UpdateChecker(opener=Mock(side_effect=exception)).check()
                self.assertEqual(result['status'],status)
                self.assertNotIn('latest_version',result)

    def test_malformed_draft_and_prerelease_are_not_offered(self):
        for response in (Reply(b'not-json'),Reply(b'[]'),release('latest'),release('v1.0.0',draft=True),release('v1.0.0-rc.1',prerelease=True),Reply(b'x'*262145)):
            with self.subTest(response=response):
                self.assertEqual(UpdateChecker(opener=Mock(return_value=response)).check()['status'],'error')

    def test_update_endpoint_requires_login_and_does_not_touch_calendars(self):
        from koma.core import Store
        from koma.server import CalendarServer
        from koma.sync import SyncManager
        from urllib.request import Request
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);user=store.create_user('update-test','Testing-password-42')
            manager=SyncManager(store);server=CalendarServer(('127.0.0.1',0),store,manager)
            server.updates=UpdateChecker(opener=Mock(return_value=release('v0.5.0')))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with self.assertRaises(HTTPError) as error:urlopen(base+'/api/updates')
                self.assertEqual(error.exception.code,401)
                token,_=store.session(user['id'])
                with urlopen(Request(base+'/api/updates',headers={'Cookie':'koma_session='+token})) as response:
                    self.assertEqual(json.load(response)['status'],'available')
                with urlopen(base+'/api/bootstrap') as response:self.assertEqual(json.load(response)['version'],VERSION)
                self.assertIsNone(store.calendar(user['id'],'combined'))
            finally:server.shutdown();server.server_close();manager.close();thread.join(timeout=3)


if __name__=='__main__':unittest.main()
