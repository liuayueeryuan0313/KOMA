import base64
import json
import struct
import tempfile
import threading
import unittest
import zlib
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from avatars import decode_avatar
from core import Store
from server import CalendarServer
from sync import SyncManager


def png(width=32,height=32,pixels=None):
    def chunk(kind,body):return struct.pack('>I',len(body))+kind+body+struct.pack('>I',zlib.crc32(kind+body)&0xffffffff)
    pixels=pixels if pixels is not None else (b'\0'+bytes([100,148,115,255])*width)*height
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')

def uri(raw):return 'data:image/png;base64,'+base64.b64encode(raw).decode()

class AvatarTests(unittest.TestCase):
    def test_bounded_png_only_and_rejects_invalid_or_bomb_payloads(self):
        self.assertEqual(decode_avatar(uri(png())),png())
        for value in ['data:image/svg+xml;base64,PHN2Zy8+',uri(b'not png'),uri(png(193,1)),uri(png()+b'extra'),uri(png(pixels=b'0'*500000)),uri(png()[:-1]),'data:image/png;base64,@@',10]:
            with self.subTest(value=str(value)[:30]),self.assertRaises(ValueError):decode_avatar(value)
    def test_user_isolation_persistence_default_restore_and_no_credentials_change(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);a=store.create_user('avatar-one','avatar-test-password');b=store.create_user('avatar-two','avatar-test-password')
            before=store.settings(a['id']);self.assertIsNone(store.user(a['id'])['avatar_version'])
            saved=store.save_avatar(a['id'],uri(png()));self.assertTrue(saved['avatar_version'])
            self.assertEqual(store.avatar(a['id']),png());self.assertIsNone(store.avatar(b['id']))
            self.assertEqual(Store(directory).avatar(a['id']),png());self.assertEqual(store.settings(a['id']),before)
            with self.assertRaises(ValueError):store.save_avatar(a['id'],'bad')
            self.assertEqual(store.avatar(a['id']),png())
            store.save_avatar(a['id'],None);self.assertIsNone(store.avatar(a['id']));self.assertIsNone(store.user(a['id'])['avatar_version'])
    def test_http_upload_requires_login_csrf_and_only_returns_own_image(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.create_user('avatar-one','avatar-test-password');store.create_user('avatar-two','avatar-test-password')
            manager=SyncManager(store);server=CalendarServer(('127.0.0.1',0),store,manager)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def request(path,method='GET',data=None,headers=None):
                return urlopen(Request(base+path,method=method,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json',**(headers or {})}),timeout=5)
            def login(name):
                with request('/api/login','POST',{'username':name,'password':'avatar-test-password'}) as response:
                    return {'Cookie':response.headers['Set-Cookie'].split(';')[0],'X-CSRF-Token':json.load(response)['csrf']}
            try:
                with self.assertRaises(HTTPError) as error:request('/api/account/avatar')
                self.assertEqual(error.exception.code,401)
                a=login('avatar-one');b=login('avatar-two')
                with self.assertRaises(HTTPError) as error:request('/api/account/avatar','PUT',{'image':uri(png())},{'Cookie':a['Cookie']})
                self.assertEqual(error.exception.code,403)
                with request('/api/account/avatar','PUT',{'image':uri(png())},a) as response:self.assertTrue(json.load(response)['user']['avatar_version'])
                with request('/api/account/avatar',headers=a) as response:
                    self.assertEqual(response.headers['Content-Type'],'image/png');self.assertEqual(response.read(),png())
                with request('/api/account/avatar',headers=b) as response:self.assertEqual(response.status,204)
                with request('/api/account/avatar','PUT',{'image':None},a) as response:self.assertIsNone(json.load(response)['user']['avatar_version'])
                with request('/api/account/avatar',headers=a) as response:self.assertEqual(response.status,204)
            finally:server.shutdown();server.server_close();manager.close();thread.join(timeout=3)
