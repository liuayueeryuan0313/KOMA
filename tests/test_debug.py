import json
import tempfile
import threading
import unittest
from urllib.request import Request,urlopen
from core import Store
from sync import SyncManager
from server import CalendarServer
from test_service import FakeBridge

class DebugTests(unittest.TestCase):
    def test_source_ip_opt_in_is_user_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);user=store.create_user('debug-test','Debug-test-password')
            other=store.create_user('debug-other','Debug-test-password')
            store.update_settings(user['id'],{'student_id':'25110000000','mode':'app','app_token':'test-token'})
            manager=SyncManager(store,FakeBridge());manager.submit(user['id'],['teaching']).result(timeout=5)
            server=CalendarServer(('127.0.0.1',0),store,manager)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(Request(base+'/api/login',json.dumps({'username':'debug-test','password':'Debug-test-password'}).encode(),{'Content-Type':'application/json'})) as response:
                    headers={'Content-Type':'application/json','Cookie':response.headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.load(response)['csrf']}
                feed=store.links(user['id'],base)['teaching']
                if isinstance(feed,dict):feed=feed['url']
                def latest():return store.dashboard(user['id'],base)['logs'][0]['message']
                with urlopen(feed):pass
                self.assertNotIn('源 IP',latest())
                with urlopen(Request(base+'/api/debug',json.dumps({'show_source_ip':True}).encode(),headers,method='PUT')):pass
                with urlopen(Request(feed,headers={'CF-Connecting-IP':'2001:db8::17'})):pass
                self.assertIn('源 IP：2001:db8::17',latest())
                self.assertFalse(store.debug_source_ip(other['id']))
                with urlopen(Request(base+'/api/debug',json.dumps({'show_source_ip':False}).encode(),headers,method='PUT')):pass
                with urlopen(feed):pass
                self.assertNotIn('源 IP',latest())
            finally:server.shutdown();server.server_close();manager.close();thread.join(timeout=3)
