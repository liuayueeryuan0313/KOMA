import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core import Store
from server import CalendarServer
from sync import SyncManager
from calendar_edit import save_occurrence


class CalendarEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.user = self.store.create_user('editor', 'Testing-password-42')['id']
        self.values = dict(name='手动课程', week=2, weekday=3, startPeriod=1,
                           endPeriod=2, location='教室甲', teacher='教师甲')

    def tearDown(self):
        self.temp.cleanup()

    def test_create_without_school_login_persists_and_updates_subscription(self):
        row = save_occurrence(self.store, self.user, 'teaching', self.values)
        self.assertEqual(row['name'], '手动课程')
        self.assertEqual(row['weekday'], 3)
        reloaded = Store(self.temp.name)
        dashboard = reloaded.dashboard(self.user, 'https://example.com')
        self.assertEqual(dashboard['occurrences'][0]['occurrenceId'], row['occurrenceId'])
        self.assertEqual(dashboard['calendars']['combined']['occurrences'], 1)
        self.assertIn('SUMMARY:手动课程', reloaded.calendar(self.user, 'teaching')['ics'])

    def test_edit_only_one_occurrence_of_imported_series(self):
        from test_service import teaching
        from adapters.scripts.compile_calendar import normalize, compile_calendar
        config = self.store.settings(self.user)['config']
        source = teaching(config)
        normalized = normalize(source, config)
        ics, metrics = compile_calendar(normalized, config)
        self.store.put_calendar(self.user, 'teaching', source, normalized, ics, metrics)
        first = self.store.dashboard(self.user, '')['occurrences'][0]
        links = self.store.links(self.user, '')
        edited = save_occurrence(self.store, self.user, 'teaching', {**self.values, 'name': '调课后的名字'}, first['occurrenceId'])
        rows = self.store.dashboard(self.user, '')['occurrences']
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r['name'] == '测试教学课' for r in rows), 2)
        self.assertEqual(edited['name'], '调课后的名字')
        self.assertEqual(links, self.store.links(self.user, ''))
        self.assertIn('SUMMARY:调课后的名字', self.store.calendar(self.user, 'combined')['ics'])
        with self.assertRaisesRegex(ValueError, '已变更'):
            save_occurrence(self.store, self.user, 'teaching', {**self.values, 'revision': first['revision']}, first['occurrenceId'])

    def test_lab_and_teaching_aggregate_preserves_both_and_reports_overlap(self):
        save_occurrence(self.store, self.user, 'teaching', self.values)
        row = save_occurrence(self.store, self.user, 'lab', {**self.values, 'projectName': '实验项目'})
        self.assertEqual(row['projectName'], '实验项目')
        combined = self.store.calendar(self.user, 'combined')
        self.assertEqual(json.loads(combined['metrics'])['occurrences'], 2)
        self.assertEqual(json.loads(combined['metrics'])['overlaps'], 1)
        self.assertIn('实验项目', combined['ics'])

    def test_invalid_input_and_other_user_do_not_modify_any_calendar(self):
        row = save_occurrence(self.store, self.user, 'teaching', self.values)
        before = self.store.calendar(self.user, 'teaching')
        for values in ({'name': ''}, {'week': 54}, {'weekday': 8}, {'startPeriod': 3, 'endPeriod': 1}, {'startPeriod': 98, 'endPeriod': 99}, {'week': True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                save_occurrence(self.store, self.user, 'teaching', {**self.values, **values}, row['occurrenceId'])
        other = self.store.create_user('other', 'Testing-password-42')['id']
        with self.assertRaises(ValueError):
            save_occurrence(self.store, other, 'teaching', self.values, row['occurrenceId'])
        self.assertIsNone(self.store.calendar(other, 'teaching'))
        self.assertEqual(before, self.store.calendar(self.user, 'teaching'))

    def test_edit_imported_lab_keeps_other_classes_and_rebuildable_snapshot(self):
        from test_service import FakeBridge
        manager = SyncManager(self.store, FakeBridge())
        try:
            self.store.update_settings(self.user, {'student_id': '25110000000', 'mode': 'jw', 'jw_password': 'test', 'campus_password': 'test'})
            manager.submit(self.user, ['teaching', 'lab']).result(timeout=5)
            rows = self.store.dashboard(self.user, '')['occurrences']
            lab = next(r for r in rows if r['kind'] == 'lab')
            save_occurrence(self.store, self.user, 'lab', {**self.values, 'projectName': '修改项目'}, lab['occurrenceId'])
            manager._rebuild_combined(self.user, self.store.settings(self.user)['config'])
            combined = self.store.calendar(self.user, 'combined')
            self.assertEqual(json.loads(combined['metrics'])['occurrences'], 4)
            self.assertIn('修改项目', combined['ics'])
            with self.store.db() as c:
                c.execute("UPDATE sync_state SET state='queued' WHERE user_id=? AND kind='teaching'", (self.user,))
            with self.assertRaisesRegex(ValueError, '同步进行中'):
                save_occurrence(self.store, self.user, 'lab', self.values)
        finally:
            manager.close()

    def test_http_requires_auth_csrf_and_updates_private_feed(self):
        manager = SyncManager(self.store)
        server = CalendarServer(('127.0.0.1', 0), self.store, manager)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        def request(path, method, body, headers=None):
            return urlopen(Request(base + path, json.dumps(body).encode(), method=method,
                           headers={'Content-Type': 'application/json', **(headers or {})}), timeout=5)
        try:
            with self.assertRaises(HTTPError) as error:
                request('/api/occurrences/teaching', 'POST', self.values)
            self.assertEqual(error.exception.code, 401)
            with request('/api/login', 'POST', {'username': 'editor', 'password': 'Testing-password-42'}) as response:
                cookie = response.headers['Set-Cookie'].split(';')[0]
                csrf = json.load(response)['csrf']
            with self.assertRaises(HTTPError) as error:
                request('/api/occurrences/teaching', 'POST', self.values, {'Cookie': cookie})
            self.assertEqual(error.exception.code, 403)
            headers = {'Cookie': cookie, 'X-CSRF-Token': csrf}
            with request('/api/occurrences/teaching', 'POST', self.values, headers) as response:
                self.assertEqual(response.status, 201)
                row = json.load(response)
            with request('/api/occurrences/teaching/' + row['occurrenceId'], 'PUT', {**self.values, 'name': '新名称'}, headers) as response:
                self.assertEqual(response.status, 200)
            url = self.store.links(self.user, base)['combined']
            with urlopen(url) as response:
                self.assertIn('SUMMARY:新名称', response.read().decode())
        finally:
            server.shutdown()
            server.server_close()
            manager.close()


if __name__ == '__main__':
    unittest.main()
