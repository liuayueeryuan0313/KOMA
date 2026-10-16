import json
import re
import tempfile
import unittest

from core import Store, json_text
from calendar_edit import save_occurrence
from adapters.scripts.compile_calendar import compile_calendar, validate_calendar


class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.uid = self.store.create_user('reminders', 'Testing-password-42')['id']
        self.values = dict(name='提醒测试课程', week=2, weekday=1,
                           startPeriod=1, endPeriod=2, location='测试教室')
        save_occurrence(self.store, self.uid, 'teaching', self.values)
        save_occurrence(self.store, self.uid, 'lab', {**self.values, 'projectName': '提醒测试实验'})

    def tearDown(self):
        self.temp.cleanup()

    def test_custom_lead_time_immediately_updates_all_saved_feeds(self):
        before = {kind: self.store.calendar(self.uid, kind) for kind in ('teaching', 'lab', 'combined')}
        links = self.store.links(self.uid, '')
        self.store.update_settings(self.uid, {'reminder_enabled': True, 'reminder_minutes': 45})
        for kind, old in before.items():
            with self.subTest(kind=kind):
                updated = self.store.calendar(self.uid, kind)
                self.assertIn('TRIGGER;RELATED=START:-PT45M', updated['ics'])
                self.assertNotIn('-PT20M', updated['ics'])
                self.assertNotEqual(old['etag'], updated['etag'])
                self.assertEqual(old['normalized'], updated['normalized'])
                self.assertEqual(old['snapshot'], updated['snapshot'])
                self.assertEqual(re.findall(r'^UID:.*', old['ics'], re.M), re.findall(r'^UID:.*', updated['ics'], re.M))
        self.assertEqual(links, self.store.links(self.uid, ''))
        self.assertEqual(Store(self.temp.name).public_settings(self.uid)['config']['reminder_minutes'], 45)

    def test_disable_removes_alarms_and_reenable_retains_last_duration(self):
        self.store.update_settings(self.uid, {'reminder_minutes': 90})
        self.store.update_settings(self.uid, {'reminder_enabled': False})
        for kind in ('teaching', 'lab', 'combined'):
            self.assertNotIn('VALARM', self.store.calendar(self.uid, kind)['ics'])
        save_occurrence(self.store, self.uid, 'teaching', {**self.values, 'week': 3})
        self.assertNotIn('VALARM', self.store.calendar(self.uid, 'combined')['ics'])
        self.store.update_settings(self.uid, {'reminder_enabled': True})
        self.assertIn('-PT90M', self.store.calendar(self.uid, 'combined')['ics'])

    def test_legacy_config_defaults_to_enabled_twenty_minutes(self):
        config = self.store.settings(self.uid)['config']
        config.pop('reminder_enabled'); config.pop('reminder_minutes')
        with self.store.db() as c:
            c.execute('UPDATE settings SET config=? WHERE user_id=?', (json_text(config), self.uid))
        public = self.store.public_settings(self.uid)['config']
        self.assertTrue(public['reminder_enabled'])
        self.assertEqual(public['reminder_minutes'], 20)
        normalized = json.loads(self.store.calendar(self.uid, 'teaching')['normalized'])
        ics, _ = compile_calendar(normalized, config)
        self.assertIn('-PT20M', ics)
        self.store.update_settings(self.uid, {'reminder_minutes': 1})
        self.assertIn('-PT1M', self.store.calendar(self.uid, 'combined')['ics'])

    def test_invalid_values_leave_settings_and_feeds_unchanged(self):
        before = self.store.settings(self.uid)
        feed = self.store.calendar(self.uid, 'combined')
        for minutes in (0, -1, 10081, 1.5, True, '30', None):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                self.store.update_settings(self.uid, {'reminder_minutes': minutes})
        for enabled in ('false', 0, None):
            with self.subTest(enabled=enabled), self.assertRaises(ValueError):
                self.store.update_settings(self.uid, {'reminder_enabled': enabled})
        self.assertEqual(before, self.store.settings(self.uid))
        self.assertEqual(feed, self.store.calendar(self.uid, 'combined'))

    def test_preferences_are_isolated_and_used_by_future_school_sync(self):
        from test_service import FakeBridge
        from sync import SyncManager
        other = self.store.create_user('other-reminders', 'Testing-password-42')['id']
        save_occurrence(self.store, other, 'teaching', self.values)
        before = self.store.calendar(other, 'teaching')
        self.store.update_settings(self.uid, {'reminder_enabled': False})
        self.assertEqual(before, self.store.calendar(other, 'teaching'))
        self.assertTrue(self.store.public_settings(other)['config']['reminder_enabled'])
        manager = SyncManager(self.store, FakeBridge())
        try:
            self.store.update_settings(self.uid, {'student_id': '25110000000', 'mode': 'jw', 'jw_password': 'test', 'campus_password': 'test'})
            manager.submit(self.uid, ['teaching', 'lab']).result(timeout=5)
            for kind in ('teaching', 'lab', 'combined'):
                self.assertNotIn('VALARM', self.store.calendar(self.uid, kind)['ics'])
        finally:
            manager.close()

    def test_validator_checks_selected_duration_and_disabled_state(self):
        normalized = json.loads(self.store.calendar(self.uid, 'teaching')['normalized'])
        config = {**self.store.settings(self.uid)['config'], 'reminder_minutes': 10080}
        ics, _ = compile_calendar(normalized, config)
        self.assertIn('-PT10080M', ics)
        with self.assertRaises(ValueError):
            validate_calendar(ics.replace('-PT10080M', '-PT20M'), normalized, config)
        with self.assertRaises(ValueError):
            validate_calendar(ics, normalized, {**config, 'reminder_enabled': False})


if __name__ == '__main__':
    unittest.main()
