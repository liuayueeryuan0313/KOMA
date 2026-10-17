import json
import tempfile
import threading
import unittest
from email.message import Message
from urllib.request import Request, urlopen

from koma.core import Store
from koma.server import CalendarServer, Handler
from koma.sync import SyncManager


class ClientIpTests(unittest.TestCase):
    def info(self, headers=None, peer='192.0.2.1'):
        handler=object.__new__(Handler)
        handler.headers=Message()
        for name,value in (headers or {}).items():handler.headers[name]=value
        handler.client_address=(peer,12345)
        return handler.client_ip_info()

    def test_cloudflare_ipv6_is_complete_and_takes_priority(self):
        ip='2409:8a00:1234:5678:90ab:cdef:1234:5678'
        self.assertEqual(self.info({'CF-Connecting-IP':' '+ip+' ', 'X-Forwarded-For':'198.51.100.1, 2001:db8::2', 'CF-IPCountry':' cn '}),
                         {'ip':ip,'proto':'IPv6','country':'CN'})

    def test_cloudflare_actual_ipv4_beats_forwarded_ipv6(self):
        self.assertEqual(self.info({'CF-Connecting-IP':'198.51.100.2','X-Forwarded-For':'2001:db8::1','CF-IPCountry':'SG'}),
                         {'ip':'198.51.100.2','proto':'IPv4','country':'SG'})

    def test_forwarded_chain_prefers_first_valid_ipv6_then_first_ipv4(self):
        self.assertEqual(self.info({'X-Forwarded-For':'198.51.100.2, 2001:db8::1, 2001:db8::2'})['ip'],'2001:db8::1')
        self.assertEqual(self.info({'X-Forwarded-For':'198.51.100.2, 192.0.2.3'})['ip'],'198.51.100.2')

    def test_invalid_header_values_fall_back_without_markup(self):
        self.assertEqual(self.info({'CF-Connecting-IP':'<script>','X-Forwarded-For':'bad:ip, 192.0.2.3','CF-IPCountry':'<img>'}),
                         {'ip':'192.0.2.3','proto':'IPv4','country':''})
        self.assertEqual(self.info({'X-Forwarded-For':' ,bad:ip, '},peer='2001:db8::99'),
                         {'ip':'2001:db8::99','proto':'IPv6','country':''})
        self.assertEqual(self.info(),{'ip':'192.0.2.1','proto':'IPv4','country':''})

    def test_bootstrap_exposes_connection_without_login_and_keeps_existing_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);manager=SyncManager(store)
            server=CalendarServer(('127.0.0.1',0),store,manager)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                request=Request(f'http://127.0.0.1:{server.server_port}/api/bootstrap',headers={
                    'CF-Connecting-IP':'2001:db8:1234::abcd','CF-IPCountry':'JP'})
                with urlopen(request) as response:
                    payload=json.load(response)
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                self.assertEqual((payload['client_ip'],payload['ip_proto'],payload['country']),('2001:db8:1234::abcd','IPv6','JP'))
                self.assertTrue({'setup_required','registration_open','disclaimer','disclaimer_version','developer','version'}<=payload.keys())
            finally:
                server.shutdown();server.server_close();manager.close();thread.join(timeout=3)


if __name__=='__main__':unittest.main()
