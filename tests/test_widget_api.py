import json
import hashlib
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from datetime import date, timedelta
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from koma.core import Store
from koma.server import CalendarServer
from koma.widget_api import WidgetAPI
from koma.calendar_edit import save_occurrence, delete_occurrence

PASSWORD = 'Widget-test-password-42'

class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.a = self.store.create_user('widget-a', PASSWORD)['id']
        self.b = self.store.create_user('widget-b', PASSWORD)['id']
        self.api = WidgetAPI(self.store)
    def tearDown(self):
        self.temp.cleanup()
    def seed(self, uid, day, project='分光计测量三棱镜的顶角'):
        rows = [{'occurrenceId': 'demo-course', 'courseId': 'physics', 'name': '【实验】大学物理实验(A)II · ' + project,
                 'projectName': project, 'location': '15号楼15-438', 'teacher': 'PRIVATE-TEACHER',
                 'startLocal': day + 'T14:00:00', 'endLocal': day + 'T15:40:00', 'startPeriod': 5, 'endPeriod': 6}]
        with self.store.db() as c:
            c.execute('INSERT OR REPLACE INTO calendars VALUES(?,?,?,?,?,?,?,?)',
                      (uid, 'lab', 'unused', 'etag', '{}', json.dumps({'occurrences': rows}), '{}', '2026-10-28T01:00:00Z'))
            c.execute("UPDATE sync_state SET state='ok',last_success='2026-10-28T01:00:00Z' WHERE user_id=? AND kind='lab'", (uid,))
    def test_token_restart_rotation_revoke_disable_and_isolation(self):
        token = self.api.rotate(self.a)['token']
        self.assertEqual(self.api.authenticate('Bearer ' + token), self.a)
        restored = WidgetAPI(Store(self.temp.name))
        self.assertEqual(restored.authenticate('Bearer ' + token), self.a)
        self.assertFalse(restored.status(self.b)['configured'])
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT token_hash FROM widget_tokens').fetchone()[0], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, json.dumps(restored.status(self.a)))
        new = restored.rotate(self.a)['token']
        self.assertIsNone(restored.authenticate('Bearer ' + token))
        with self.store.db() as c: c.execute('UPDATE users SET disabled=1 WHERE id=?', (self.a,))
        self.assertIsNone(restored.authenticate('Bearer ' + new))
        restored.revoke(self.a)
        self.assertFalse(restored.status(self.a)['configured'])
        self.assertIsNone(restored.authenticate('Bearer ' + new))
        other = restored.rotate(self.b)['token']
        with self.store.db() as c: c.execute('DELETE FROM users WHERE id=?', (self.b,))
        self.assertIsNone(restored.authenticate('Bearer ' + other))
        self.assertFalse(restored.status(self.b)['configured'])

    def test_saved_edits_deletions_and_all_courses_without_school_access(self):
        from unittest.mock import patch
        from adapters.scripts.compile_calendar import normalize, compile_calendar
        from test_service import teaching
        config = self.store.settings(self.a)['config']
        source = teaching(config)
        normalized = normalize(source, config)
        ics, metrics = compile_calendar(normalized, config)
        self.store.put_calendar(self.a, 'teaching', source, normalized, ics, metrics)
        rows = self.store.dashboard(self.a, '')['occurrences']
        target = rows[0]
        values = dict(name='修改后的课程', week=target['week'], weekday=target['weekday'],
                      startPeriod=target['startPeriod'], endPeriod=target['endPeriod'], location='新教室')
        edited = save_occurrence(self.store, self.a, 'teaching', values, target['occurrenceId'])
        for i in range(6):
            save_occurrence(self.store, self.a, 'teaching', {**values, 'name': '新增课程'+str(i)})
        with patch.object(self.store, 'settings', side_effect=AssertionError('must not load credentials')):
            payload = self.api.timetable(self.a, 'days=1', today=date.fromisoformat(edited['date']))
        courses = payload['days'][0]['courses']
        self.assertEqual(len(courses), 7)
        self.assertTrue(all(c['timeOverlap'] for c in courses))
        self.assertIn('修改后的课程', [c['name'] for c in courses])
        delete_occurrence(self.store, self.a, 'teaching', target['occurrenceId'], edited['revision'])
        self.store.put_calendar(self.a, 'teaching', source, normalized, ics, metrics)
        courses = self.api.timetable(self.a, 'days=1', today=date.fromisoformat(edited['date']))['days'][0]['courses']
        self.assertNotIn(target['occurrenceId'], [c['id'] for c in courses])
        self.assertEqual(len(courses), 6)
    def test_three_days_cross_week_and_project_only_no_teacher(self):
        self.seed(self.a, '2026-11-02')
        payload = self.api.timetable(self.a, today=date(2026, 10, 31))
        self.assertEqual([x['date'] for x in payload['days']], ['2026-10-31','2026-11-01','2026-11-02'])
        course = payload['days'][2]['courses'][0]
        self.assertEqual(course['name'], '分光计测量三棱镜的顶角')
        self.assertNotIn('PRIVATE-TEACHER', json.dumps(payload))
        self.assertNotIn('大学物理实验', json.dumps(payload, ensure_ascii=False))
        self.assertEqual(course['startAt'], '2026-11-02T14:00:00+08:00')
        self.assertEqual(payload['state'], 'partial')
        other = self.api.timetable(self.b, today=date(2026, 10, 31))
        self.assertEqual(other['state'], 'unavailable')
        self.assertFalse(any(d['courses'] for d in other['days']))
    def test_local_helper_does_not_reset_running_jobs(self):
        import subprocess
        with self.store.db() as c:
            c.execute("UPDATE sync_state SET state='running' WHERE user_id=?", (self.a,))
        command = [sys.executable, str(Path(__file__).resolve().parents[1]/'tools/widget_token.py'),
                   'rotate', '--username', 'widget-a', '--data-dir', self.temp.name]
        value = json.loads(subprocess.check_output(command, text=True))
        self.assertEqual(self.api.authenticate('Bearer '+value['token']), self.a)
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT state FROM sync_state WHERE user_id=?', (self.a,)).fetchone()[0], 'running')
    def test_query_validation(self):
        for query in ('days=0','days=8','days=x','days=3&days=4','offset=999','token=secret','user_id=other'):
            with self.subTest(query=query), self.assertRaises(ValueError): self.api.timetable(self.a, query)
    def test_http_management_csrf_bearer_is_not_admin(self):
        server = CalendarServer(('127.0.0.1', 0), self.store, object())
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, body=None, headers=None, method=None):
            return urlopen(Request(base+path, data=json.dumps(body).encode() if body is not None else None,
                headers={'Content-Type':'application/json', **(headers or {})}, method=method), timeout=5)
        try:
            with request('/api/login', {'username':'widget-a','password':PASSWORD}) as r:
                cookie=r.headers['Set-Cookie'].split(';')[0]; csrf=json.load(r)['csrf']
            with self.assertRaises(HTTPError) as e: request('/api/widget/token', {'action':'rotate'}, {'Cookie':cookie})
            self.assertEqual(e.exception.code,403)
            with request('/api/widget/token', {'action':'rotate'}, {'Cookie':cookie,'X-CSRF-Token':csrf}) as r: token=json.load(r)['token']
            with request('/api/widget/token', headers={'Cookie':cookie}) as r:
                status=json.load(r);self.assertTrue(status['configured']);self.assertNotIn('token',status)
            with self.assertRaises(HTTPError) as e:
                request('/api/widget/token', {'action':'rotate'}, {'Cookie':cookie,'X-CSRF-Token':csrf,'Origin':'https://other.invalid'})
            self.assertEqual(e.exception.code,403)
            with request('/api/widget/v1/timetable', headers={'Authorization':'Bearer '+token}, method='HEAD') as r:
                self.assertEqual(r.status,200);self.assertEqual(r.read(),b'');self.assertEqual(r.headers['Cache-Control'],'no-store')
            with request('/api/widget/v1/timetable', headers={'Authorization':'Bearer '+token}) as r:
                self.assertEqual(json.load(r)['schemaVersion'],1); self.assertEqual(r.headers['Cache-Control'],'no-store')
            for headers in ({},{'Cookie':cookie},{'Authorization':'Bearer bad'}):
                with self.assertRaises(HTTPError) as e: request('/api/widget/v1/timetable', headers=headers)
                self.assertEqual(e.exception.code,401);self.assertEqual(e.exception.headers['Cache-Control'],'no-store')
            with self.assertRaises(HTTPError) as e:
                request('/api/widget/v1/timetable?user_id='+self.b, headers={'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,400)
            for path in ('/api/dashboard','/api/widget/token'):
                with self.assertRaises(HTTPError) as e: request(path, headers={'Authorization':'Bearer '+token})
                self.assertEqual(e.exception.code,401)
            with self.assertRaises(HTTPError) as e: request('/api/settings', {}, {'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,401)
            with request('/api/widget/token', {'action':'revoke'}, {'Cookie':cookie,'X-CSRF-Token':csrf}): pass
            with self.assertRaises(HTTPError) as e: request('/api/widget/v1/timetable', headers={'Authorization':'Bearer '+token})
            self.assertEqual(e.exception.code,401)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

if __name__ == '__main__': unittest.main()
