import copy
import json
import re
import tempfile
import unittest

from koma.core import Store
from koma.calendar_edit import save_occurrence
from koma.calendar_layers import resolve_occurrence
from adapters.scripts.compile_calendar import normalize,compile_calendar
from test_service import teaching,FakeBridge
from koma.sync import SyncManager


class CalendarLayerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.uid=self.store.create_user('layers','Testing-password-42')['id']
        self.config=self.store.settings(self.uid)['config']
        self.snapshot=teaching(self.config)
        self.publish(self.snapshot)
    def tearDown(self):self.temp.cleanup()
    def publish(self,snapshot,kind='teaching'):
        config=self.store.settings(self.uid)['config']
        normalized=normalize(snapshot,config);ics,metrics=compile_calendar(normalized,config)
        self.store.put_calendar(self.uid,kind,snapshot,normalized,ics,metrics)
    def rows(self):return self.store.dashboard(self.uid,'')['occurrences']
    def values(self,row,**updates):
        return {**{k:row.get(k,'') for k in ('name','week','weekday','startPeriod','endPeriod','location','teacher','courseName','projectName')},'revision':row['revision'],**updates}
    def edit(self,row,**updates):return save_occurrence(self.store,self.uid,row['kind'],self.values(row,**updates),row['occurrenceId'])
    def first(self):return next(r for r in self.rows() if r['week']==1 and r['kind']=='teaching')

    def test_manual_new_survives_repeated_sync_and_restart(self):
        manual=save_occurrence(self.store,self.uid,'teaching',self.values(self.first(),week=2,name='自定义安排'))
        self.publish(self.snapshot);self.publish(self.snapshot)
        reloaded=Store(self.temp.name).dashboard(self.uid,'')['occurrences']
        self.assertEqual(sum(r['occurrenceId']==manual['occurrenceId'] for r in reloaded),1)
        self.assertEqual(len(reloaded),4)
        self.assertIn('SUMMARY:自定义安排',self.store.calendar(self.uid,'combined')['ics'])

    def test_field_override_follows_untouched_school_fields_and_identity(self):
        before=self.first();edited=self.edit(before,location='我的教室')
        changed=copy.deepcopy(self.snapshot);changed['rows'][0].update(teacher='新教师',kcmc='新课程名')
        self.publish(changed);actual=self.first()
        self.assertEqual(actual['occurrenceId'],before['occurrenceId'])
        self.assertEqual(actual['location'],'我的教室')
        self.assertEqual(actual['teacher'],'新教师')
        self.assertEqual(actual['name'],'新课程名')
        self.assertEqual(actual['conflictFields'],[])
        self.assertEqual(edited['eventUid'],actual['eventUid'])
        with self.store.db() as c:
            raw=json.loads(c.execute('SELECT snapshot FROM school_sources WHERE user_id=? AND kind=? AND term=?',(self.uid,'teaching',self.config['term'])).fetchone()[0])
        self.assertEqual(raw['rows'][0]['jxdd'],'测试教室')

    def test_school_reschedule_tracks_same_lesson_without_duplicates(self):
        old=self.first();self.edit(old,location='我的教室')
        changed=copy.deepcopy(self.snapshot);changed['rows'][0].update(xq='星期二',ksjc='3',jsjc='4')
        self.publish(changed)
        actual=self.first()
        self.assertEqual(actual['occurrenceId'],old['occurrenceId'])
        self.assertEqual(actual['weekday'],2)
        self.assertEqual(actual['startPeriod'],3)
        self.assertEqual(actual['location'],'我的教室')
        self.assertEqual(len(self.rows()),3)
        self.assertEqual(actual['conflictFields'],[])

    def test_time_conflict_keeps_manual_time_and_can_restore_latest_school(self):
        old=self.first();edited=self.edit(old,weekday=3,startPeriod=5,endPeriod=6)
        changed=copy.deepcopy(self.snapshot);changed['rows'][0].update(xq='星期二',ksjc='3',jsjc='4')
        self.publish(changed);actual=self.first()
        self.assertEqual(actual['weekday'],3)
        self.assertEqual(actual['schoolArrangement']['weekday'],2)
        self.assertIn('weekday',actual['conflictFields'])
        self.assertEqual(actual['eventUid'],edited['eventUid'])
        resolve_occurrence(self.store,self.uid,'teaching',actual['occurrenceId'],'restore',actual['revision'])
        restored=self.first()
        self.assertEqual(restored['weekday'],2)
        self.assertEqual(restored['origin'],'school')
        self.assertEqual(restored['occurrenceId'],old['occurrenceId'])
        self.assertEqual(len(self.rows()),3)

    def test_keep_acknowledges_current_conflict_but_next_change_warns_again(self):
        self.edit(self.first(),location='我的教室')
        changed=copy.deepcopy(self.snapshot);changed['rows'][0]['jxdd']='学校新教室'
        self.publish(changed);actual=self.first()
        self.assertEqual(actual['conflictFields'],['location'])
        resolve_occurrence(self.store,self.uid,'teaching',actual['occurrenceId'],'keep',actual['revision'])
        self.assertEqual(self.first()['conflictFields'],[])
        self.publish(changed);self.assertEqual(self.first()['conflictFields'],[])
        changed['rows'][0]['jxdd']='学校再次修改教室';self.publish(changed)
        self.assertEqual(self.first()['conflictFields'],['location'])

    def test_deleted_school_lesson_retained_pending_then_restore_removes_it(self):
        self.edit(self.first(),location='我的教室')
        changed=copy.deepcopy(self.snapshot);changed['rows']=changed['rows'][1:]
        self.publish(changed);actual=self.first()
        self.assertTrue(actual['schoolMissing'])
        self.assertIn('missing',actual['conflictFields'])
        self.assertEqual(len(self.rows()),3)
        resolve_occurrence(self.store,self.uid,'teaching',actual['occurrenceId'],'restore',actual['revision'])
        self.assertEqual(len(self.rows()),2)
        self.assertEqual(self.store.dashboard(self.uid,'')['calendars']['combined']['conflicts'],0)

    def test_ambiguous_same_name_or_code_is_not_silently_matched(self):
        snapshot=copy.deepcopy(self.snapshot)
        snapshot['rows']=[snapshot['rows'][0],{**snapshot['rows'][0],'xq':'星期二','ksjc':'3','jsjc':'4'}]
        self.publish(snapshot);old=self.first();self.edit(old,location='我的教室')
        shifted=copy.deepcopy(snapshot)
        shifted['rows'][0].update(xq='星期三',ksjc='5',jsjc='6')
        shifted['rows'][1].update(xq='星期四',ksjc='7',jsjc='8')
        self.publish(shifted)
        self.assertTrue(any(r['schoolMissing'] for r in self.rows()))
        self.assertEqual(sum(r['origin']=='school' for r in self.rows()),2)
        self.assertEqual(sum(r['origin']=='override' for r in self.rows()),1)

    def test_explicit_source_id_wins_even_when_course_code_and_date_change(self):
        self.snapshot['rows'][0]['sourceOccurrenceId']='verified-schedule-123'
        self.publish(self.snapshot);old=self.first();self.edit(old,location='我的教室')
        changed=copy.deepcopy(self.snapshot);changed['rows'][0].update(kcdm='new-code',skzc='2',xq='星期五',ksjc='3',jsjc='4')
        self.publish(changed)
        row=next(r for r in self.rows() if r['occurrenceId']==old['occurrenceId'])
        self.assertEqual(row['courseId'],'new-code')
        self.assertEqual(row['week'],2)
        self.assertEqual(row['location'],'我的教室')
        self.assertEqual(len(self.rows()),3)

    def test_stale_revision_and_cross_account_resolution_are_rejected(self):
        old=self.first();self.edit(old,location='我的教室')
        with self.assertRaisesRegex(ValueError,'已变更'):self.edit(old,name='旧表单')
        other=self.store.create_user('other-layers','Testing-password-42')['id']
        with self.assertRaises(ValueError):resolve_occurrence(self.store,other,'teaching',old['occurrenceId'],'restore')

    def test_real_sync_pipeline_preserves_manual_and_override(self):
        self.store.update_settings(self.uid,{'student_id':'25110000000','mode':'jw','jw_password':'test','campus_password':'test'})
        manager=SyncManager(self.store,FakeBridge())
        try:
            manager.submit(self.uid,['teaching','lab']).result(timeout=5)
            original=self.first();self.edit(original,location='我的教室')
            save_occurrence(self.store,self.uid,'teaching',self.values(self.first(),week=2,name='手动课'))
            manager.submit(self.uid,['teaching','lab']).result(timeout=5)
            self.assertEqual(self.first()['location'],'我的教室')
            self.assertEqual(len(self.rows()),5)
            combined=self.store.calendar(self.uid,'combined')
            self.assertIn('手动课',combined['ics'])
            self.assertIn('我的教室',combined['ics'])
        finally:manager.close()

    def test_legacy_manual_rows_migrate_once_and_survive_new_school_data(self):
        other=self.store.create_user('legacy-layers','Testing-password-42')['id']
        config=self.store.settings(other)['config']
        snapshot=teaching(config);snapshot['rows']=snapshot['rows'][:1]
        snapshot['rows'][0].update(manual=True,kcdm='teaching:manual:legacy',kcmc='旧版手动课程')
        normalized=normalize(snapshot,config);ics,metrics=compile_calendar(normalized,config)
        from koma.core import digest,json_text,now
        with self.store.db() as c:
            c.execute('INSERT INTO calendars VALUES(?,?,?,?,?,?,?,?)',(other,'teaching',ics,digest(ics),json_text(snapshot),json_text(normalized),json_text(metrics),now()))
        reloaded=Store(self.temp.name)
        rows=reloaded.dashboard(other,'')['occurrences']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['origin'],'manual')
        identifier=rows[0]['occurrenceId']
        self.assertEqual(Store(self.temp.name).dashboard(other,'')['occurrences'][0]['occurrenceId'],identifier)
        source=teaching(config);normalized=normalize(source,config);ics,metrics=compile_calendar(normalized,config)
        reloaded.put_calendar(other,'teaching',source,normalized,ics,metrics)
        self.assertEqual(len(reloaded.dashboard(other,'')['occurrences']),4)

    def test_restore_rejects_an_outdated_comparison(self):
        edited=self.edit(self.first(),location='我的教室')
        changed=copy.deepcopy(self.snapshot);changed['rows'][0]['jxdd']='学校更新的教室'
        self.publish(changed)
        with self.assertRaisesRegex(ValueError,'已变更'):
            resolve_occurrence(self.store,self.uid,'teaching',edited['occurrenceId'],'restore',edited['revision'])
        self.assertEqual(self.first()['location'],'我的教室')

    def test_term_and_school_changes_do_not_reuse_other_term_edits(self):
        self.edit(self.first(),location='旧学期手动教室')
        self.store.update_settings(self.uid,{'term':'2026-2027-2','week1_monday':'2027-02-22'})
        save_occurrence(self.store,self.uid,'teaching',dict(name='新学期课程',week=1,weekday=1,startPeriod=1,endPeriod=2,location='新教室'))
        self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.rows()[0]['name'],'新学期课程')
        self.store.update_settings(self.uid,{'student_id':'25110000000'})
        with self.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM manual_occurrences WHERE user_id=?',(self.uid,)).fetchone()[0],0)


if __name__=='__main__':unittest.main()
