import copy
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,now
from sync import SyncManager,SourceError
from server import CalendarServer
from school_profiles import DEFAULTS,effective_school,prepare_school_config

PASSWORD='Test-account-password-42'
def teaching(config):
    return {'xnxq':config['term'],'beginDate':config['week1_monday'],'endDate':'2027-01-17','maxWeekNumber':20,'sourceAdapter':'app-h5','rows':[{'xnxq':config['term'],'kcdm':'test-course','kcmc':'测试教学课','skzc':str(w),'xq':'星期一','ksjc':'1','jsjc':'2','jxdd':'测试教室'} for w in [1,3,5]]}
def lab_payload(config):
    row={'course_name':'测试实验课','exp_name':'独立实验项目','week':7,'week_day':2,'jc_start':'11','jc_end':'12','room_name':'测试实验室','teacher_name':'测试教师','form':1,'row_id':1}
    return {'adapter':'lab-har','calendarTerm':config['term'],'pages':[{'request':{'yearterm':config['term'],'currpage':1,'pagesize':15},'result':{'totalCount':1,'totalPage':1,'pageSize':15,'currPage':1,'list':[row]}}],'identity':{'name':'测试学生','studentId':'25110000000'}}
def jw_payload(config):
    return {'adapter':'jw-web','calendarTerm':config['term'],'maxWeekNumber':20,'request':{'xnm':'2026','xqm':'3'},'kbList':[{'kch':'test-course','kcmc':'测试教学课','xqj':'1','jcs':'1-2','zcd':'1-5周(单)','cdmc':'测试教室','xm':'测试教师','xnm':'2026','xqm':'3'}],'periods':[],'identity':{'name':'测试学生','studentId':'25110000000'}}
class FakeBridge:
    def __init__(self):self.calls=[];self.credential_inputs=[];self.config_inputs=[];self.app_error=None;self.lab_error=None;self.jw_error=None;self.bad_lab=False
    def call(self,operation,creds,config):
        self.calls.append(operation)
        self.credential_inputs.append(dict(creds))
        self.config_inputs.append(copy.deepcopy(config))
        if operation.startswith('connect_'):return {'reachable':True}
        if operation in ('jw_login','lab_login'):
            error=self.jw_error if operation=='jw_login' else self.lab_error
            if error:raise SourceError(error)
            return {'payload':{'identity':{'name':'测试学生','studentId':'25110000000'}}}
        if operation=='app_init':return {'token':'replacement-test-token','identity':{'name':'测试学生','studentId':'25110000000'}}
        if operation=='app_fetch':
            if self.app_error:raise SourceError(self.app_error)
            return {'snapshot':teaching(config),'identity':{'name':'测试学生','studentId':'25110000000'}}
        if operation=='jw_fetch':
            if self.jw_error:raise SourceError(self.jw_error)
            return {'payload':jw_payload(config)}
        if operation=='lab_fetch':
            if self.lab_error:raise SourceError(self.lab_error)
            payload=lab_payload(config)
            if self.bad_lab:payload['pages'][0]['result']['totalPage']=2
            return {'payload':payload}
        raise AssertionError(operation)

class ServiceTests(unittest.TestCase):
    def setUp(self):
        test_root=Path(__file__).resolve().parents[1]/'.test-data';test_root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=test_root);self.store=Store(self.temp.name)
        self.user=self.store.create_user('tester',PASSWORD);self.uid=self.user['id']
        self.store.update_settings(self.uid,{'student_id':'25110000000','campus_password':'Sensitive-campus-password','jw_password':'Sensitive-jw-password'})
        self.fake=FakeBridge();self.manager=SyncManager(self.store,self.fake)
    def tearDown(self):
        self.manager.close()
        self.assertEqual(Path(self.temp.name).resolve().parent,(Path(__file__).resolve().parents[1]/'.test-data').resolve())
        self.temp.cleanup()
    def sync(self,*kinds,initialize=False):self.manager.submit(self.uid,list(kinds),initialize).result(timeout=5)
    def shared_plan(self,mode='app',teaching_interval=60,lab_interval=60,lab_enabled=True):
        self.store.update_settings(self.uid,{'mode':mode,'app_token':'shared-existing-token',
            'teaching':{'enabled':True,'interval_minutes':teaching_interval},
            'lab':{'enabled':lab_enabled,'interval_minutes':lab_interval}})
    def test_same_interval_app_sync_reuses_token_and_logs_in_cas_once(self):
        self.shared_plan();self.sync('teaching')
        self.assertEqual(self.fake.calls,['app_fetch','lab_fetch'])
        self.assertEqual(self.fake.credential_inputs[0]['token'],'shared-existing-token')
        states=self.store.dashboard(self.uid,'http://localhost')['states']
        self.assertEqual(states['teaching']['next_run'],states['lab']['next_run'])
        self.assertEqual(states['teaching']['state'],'ok');self.assertEqual(states['lab']['state'],'ok')
        self.assertTrue(any(r['event']=='SHARED_SYNC_STARTED' for r in self.store.dashboard(self.uid,'http://localhost')['logs']))
    def test_shared_scheduler_heals_staggered_due_dates_without_second_login(self):
        self.shared_plan()
        with self.store.db() as c:c.execute("UPDATE sync_state SET next_run=? WHERE user_id=? AND kind='lab'",('2020-01-01T00:00:00+00:00',self.uid))
        self.manager.schedule_due();self.manager.pool.shutdown(wait=True)
        self.assertEqual(self.fake.calls,['app_fetch','lab_fetch'])
        self.manager.schedule_due()
        self.assertEqual(self.fake.calls,['app_fetch','lab_fetch'])
        states=self.store.dashboard(self.uid,'http://localhost')['states']
        self.assertEqual(states['teaching']['next_run'],states['lab']['next_run'])
    def test_different_intervals_and_disabled_plans_stay_independent(self):
        for ti,li,enabled in [(30,60,True),(60,60,False)]:
            with self.subTest(teaching=ti,lab=li,enabled=enabled):
                self.fake.calls=[];self.shared_plan(teaching_interval=ti,lab_interval=li,lab_enabled=enabled)
                self.sync('teaching');self.assertEqual(self.fake.calls,['app_fetch'])
    def test_jw_mode_remains_independent_with_matching_intervals(self):
        self.shared_plan(mode='jw');self.sync('lab')
        self.assertEqual(self.fake.calls,['lab_fetch'])
    def test_auto_mode_only_groups_while_token_is_usable(self):
        self.shared_plan(mode='auto')
        self.store.save_teacher_cache(self.uid,[{'kcdm':'cached','teacher':'教师'}])
        self.sync('lab');self.assertEqual(self.fake.calls,['app_fetch','lab_fetch'])
        self.fake.calls=[];self.store.save_secret(self.uid,{'token_invalid':True})
        self.sync('lab');self.assertEqual(self.fake.calls,['lab_fetch'])
    def test_shared_auth_failure_does_not_retry_and_keeps_other_calendar(self):
        self.shared_plan();self.sync('teaching');previous=self.store.calendar(self.uid,'lab')['ics']
        self.fake.calls=[];self.fake.lab_error='HUMAN_CAPTCHA_REQUIRED';self.sync('lab')
        self.assertEqual(self.fake.calls,['app_fetch','lab_fetch'])
        self.assertEqual(self.store.calendar(self.uid,'lab')['ics'],previous)
        states=self.store.dashboard(self.uid,'http://localhost')['states']
        self.assertEqual(states['lab']['state'],'error');self.assertEqual(states['teaching']['state'],'ok')
        self.assertEqual(states['teaching']['next_run'],states['lab']['next_run'])
    def test_explicit_app_relogin_never_expands_a_single_source_task(self):
        self.shared_plan();self.sync('teaching',initialize=True)
        self.assertEqual(self.fake.calls,['app_init','app_fetch'])
    def test_unusable_token_does_not_expand_single_source_task(self):
        self.shared_plan();self.store.save_secret(self.uid,{'token':'','token_invalid':True})
        self.sync('lab');self.assertEqual(self.fake.calls,['lab_fetch'])
    def test_default_school_does_not_reset_existing_credentials_or_links(self):
        self.store.save_secret(self.uid,{'token':'existing-test-token'})
        links=self.store.links(self.uid,'http://localhost');self.sync('lab')
        self.store.update_settings(self.uid,{'school_profile':'sdut'})
        self.assertEqual(effective_school(self.store.settings(self.uid)['config']),DEFAULTS)
        self.assertEqual(self.store.links(self.uid,'http://localhost'),links)
        self.assertEqual(self.store.settings(self.uid)['credentials']['token'],'existing-test-token')
        self.assertIsNotNone(self.store.calendar(self.uid,'lab'))
    def test_school_destination_change_clears_old_secrets_and_calendars(self):
        self.store.save_secret(self.uid,{'token':'old-school-token','token_invalid':True});self.sync('lab')
        links=self.store.links(self.uid,'http://localhost')
        self.store.update_settings(self.uid,{'school_profile':'custom','school_custom':{'name':'测试学校','jw_base':'https://jw.example.edu.cn/newjw'},'jw_password':'New-school-password'})
        saved=self.store.settings(self.uid)
        self.assertEqual(saved['credentials'],{'student_id':'25110000000','jw_password':'New-school-password'})
        self.assertIsNone(self.store.calendar(self.uid,'lab'));self.assertNotEqual(links,self.store.links(self.uid,'http://localhost'))
        self.assertEqual(effective_school(saved['config'])['app_h5_base'],'')
        self.assertEqual(effective_school(saved['config'])['jw_base'],'https://jw.example.edu.cn/newjw')
        other=self.store.create_user('school-other',PASSWORD)
        self.assertEqual(effective_school(self.store.settings(other['id'])['config']),DEFAULTS)
    def test_school_display_name_change_keeps_secrets_and_data(self):
        self.store.update_settings(self.uid,{'school_profile':'custom','school_custom':{'name':'学校甲','jw_base':'https://jw.example.edu.cn/jwglxt'},'jw_password':'New-school-password','mode':'jw'})
        self.sync('teaching');links=self.store.links(self.uid,'http://localhost')
        self.store.update_settings(self.uid,{'school_custom':{'name':'学校新名称'}})
        self.assertEqual(self.store.links(self.uid,'http://localhost'),links)
        self.assertEqual(self.store.settings(self.uid)['credentials']['jw_password'],'New-school-password')
        self.assertIsNotNone(self.store.calendar(self.uid,'teaching'))
    def test_school_config_rejects_unsafe_urls_and_paths_atomically(self):
        before=self.store.settings(self.uid)
        for url in ['http://jw.example.edu.cn','https://localhost','https://127.0.0.1','https://169.254.169.254','https://192.168.1.1','https://user:pass@jw.example.edu.cn','https://jw.example.edu.cn?token=test','https://jw.example.edu.cn/#route','https://jw.example.edu.cn/%2e%2e','https://jw.example.edu.cn/../admin']:
            with self.subTest(url=url),self.assertRaises(ValueError):self.store.update_settings(self.uid,{'school_profile':'custom','school_custom':{'name':'测试学校','jw_base':url}})
        for path in ['/../','/a/..','https://other.example.edu.cn/path']:
            with self.subTest(path=path),self.assertRaises(ValueError):self.store.update_settings(self.uid,{'school_profile':'custom','school_custom':{'name':'测试学校','lab_cas_entry':path}})
        self.assertEqual(self.store.settings(self.uid),before)
    def test_transient_school_test_uses_override_without_publishing(self):
        saved=self.store.settings(self.uid)
        config=prepare_school_config(saved['config'],{'school_profile':'custom','school_custom':{'name':'测试学校','jw_base':'https://jw.example.edu.cn/alternate'}})
        self.manager.submit_platform(self.uid,'jw','test',{'student_id':'25110000000','jw_password':'Transient-school-password'},config).result(timeout=5)
        self.assertEqual(self.fake.config_inputs[-1]['school_custom']['jw_base'],'https://jw.example.edu.cn/alternate')
        self.assertEqual(self.store.settings(self.uid),saved);self.assertIsNone(self.store.calendar(self.uid,'teaching'))
        self.assertEqual(self.store.dashboard(self.uid,'http://localhost')['platform_checks']['jw']['test']['state'],'ok')
    def test_custom_clock_times_are_validated_and_used_for_calendar(self):
        self.store.update_settings(self.uid,{'period_times':'1 09:00 09:45\n2 09:55 10:40\n11-12 21:05 22:45'})
        self.sync('teaching')
        ics=self.store.calendar(self.uid,'teaching')['ics']
        self.assertIn('T090000',ics);self.assertIn('T104000',ics)
        before=self.store.settings(self.uid)
        for value in ['1 24:00 25:00','1 09:00 08:00','1 08:00 08:45\n1 09:00 09:45','12-11 21:05 22:45']:
            with self.subTest(value=value),self.assertRaises(ValueError):self.store.update_settings(self.uid,{'period_times':value})
        self.assertEqual(self.store.settings(self.uid),before)
    def test_http_custom_test_never_reuses_old_school_credentials(self):
        captured=[]
        self.manager.submit_platform=lambda *args:captured.append(args)
        server=CalendarServer(('127.0.0.1',0),self.store,self.manager)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        def request(path,body,headers=None):return urlopen(Request(base+path,json.dumps(body).encode(),headers={'Content-Type':'application/json',**(headers or {})}),timeout=5)
        try:
            with request('/api/login',{'username':'tester','password':PASSWORD}) as response:
                cookie=response.headers['Set-Cookie'].split(';')[0];csrf=json.load(response)['csrf']
            before=self.store.settings(self.uid)
            body={'school_profile':'custom','school_custom':{'name':'测试学校','jw_base':'https://jw.example.edu.cn/jwglxt'},'student_id':'25110000000'}
            with request('/api/platforms/jw/test',body,{'Cookie':cookie,'X-CSRF-Token':csrf}) as response:self.assertEqual(response.status,202)
            self.assertEqual(captured[-1][3],{'student_id':'25110000000'})
            self.assertEqual(captured[-1][4]['school_custom']['jw_base'],'https://jw.example.edu.cn/jwglxt')
            self.assertEqual(self.store.settings(self.uid),before)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)
    def test_passwords_and_tokens_are_encrypted_and_user_scoped(self):
        self.store.save_secret(self.uid,{'token':'super-secret-test-token'})
        with self.store.db() as c:row=c.execute('SELECT secret FROM settings WHERE user_id=?',(self.uid,)).fetchone()
        for value in ['Sensitive-campus-password','Sensitive-jw-password','super-secret-test-token']:self.assertNotIn(value,row['secret'])
        other=self.store.create_user('other-user',PASSWORD)
        with self.assertRaises(Exception):self.store.decrypt(row['secret'],other['id'])
        public=json.dumps(self.store.dashboard(self.uid,'http://localhost'))
        self.assertNotIn('Sensitive-campus-password',public);self.assertNotIn('super-secret-test-token',public)
    def test_auto_expired_token_fails_over_only_teaching(self):
        self.fake.app_error='TOKEN_REQUIRED';self.sync('teaching','lab')
        states=self.store.dashboard(self.uid,'http://localhost')['states']
        self.assertEqual(states['teaching']['active_source'],'jw');self.assertEqual(states['teaching']['state'],'warning')
        self.assertIn('已切换',states['teaching']['warning']);self.assertEqual(states['lab']['active_source'],'lab-cas')
        self.assertEqual(self.fake.calls,['app_fetch','jw_fetch','lab_fetch'])
        self.assertEqual(json.loads(self.store.calendar(self.uid,'combined')['metrics'])['occurrences'],4)
    def test_network_error_does_not_trigger_token_failover(self):
        self.fake.app_error='FETCH_FAILED';self.sync('teaching')
        self.assertEqual(self.fake.calls,['app_fetch']);self.assertIsNone(self.store.calendar(self.uid,'teaching'))
    def test_invalid_app_token_is_latched_until_user_supplies_new_token(self):
        self.fake.app_error='TOKEN_REQUIRED';self.sync('teaching');self.fake.calls=[]
        self.sync('teaching');self.assertEqual(self.fake.calls,['jw_fetch'])
        self.assertTrue(self.store.public_settings(self.uid)['app_token_invalid'])
        self.store.update_settings(self.uid,{'app_token':'new-manually-provided-token'});self.fake.app_error=None;self.fake.calls=[]
        self.sync('teaching');self.assertEqual(self.fake.calls,['app_fetch'])
        self.assertFalse(self.store.public_settings(self.uid)['app_token_invalid'])
        self.assertNotIn('app_init',self.fake.calls)
    def test_app_only_never_calls_jw(self):
        self.store.update_settings(self.uid,{'mode':'app'});self.sync('teaching')
        self.assertEqual(self.fake.calls,['app_fetch']);self.fake.calls=[]
        self.fake.app_error='TOKEN_REQUIRED';self.sync('teaching')
        self.assertEqual(self.fake.calls,['app_fetch'])
    def test_failed_failover_remains_visible_and_retains_calendar(self):
        self.sync('teaching');previous=self.store.calendar(self.uid,'teaching')['ics']
        self.fake.app_error='TOKEN_REQUIRED';self.fake.jw_error='LOGIN_FAILED';self.sync('teaching')
        state=self.store.dashboard(self.uid,'http://localhost')['states']['teaching']
        self.assertEqual(state['state'],'error');self.assertIn('转至教务系统后仍未同步成功',state['warning'])
        self.assertEqual(self.store.calendar(self.uid,'teaching')['ics'],previous)
    def test_student_or_term_change_clears_teacher_cache(self):
        self.store.save_teacher_cache(self.uid,[{'kcdm':'test','teacher':'旧教师'}])
        self.store.update_settings(self.uid,{'student_id':'25110000001'})
        settings=self.store.settings(self.uid);self.assertEqual(settings['config']['course_details'],{})
        self.assertNotIn('campus_password',settings['credentials'])
        self.store.save_teacher_cache(self.uid,[{'kcdm':'test','teacher':'旧教师'}])
        self.store.update_settings(self.uid,{'term':'2026-2027-2'})
        self.assertEqual(self.store.settings(self.uid)['config']['course_details'],{})
    def test_jw_only_never_calls_app(self):
        self.store.update_settings(self.uid,{'mode':'jw'});self.sync('teaching');self.assertEqual(self.fake.calls,['jw_fetch'])
    def test_experiment_failure_never_uses_teaching_source(self):
        self.fake.lab_error='HUMAN_CAPTCHA_REQUIRED';self.sync('lab');self.assertEqual(self.fake.calls,['lab_fetch'])
        self.assertIn('验证码',self.store.dashboard(self.uid,'http://localhost')['states']['lab']['warning'])
    def test_failure_retains_previous_calendar_and_success_time(self):
        self.sync('lab');old=self.store.calendar(self.uid,'lab');state=self.store.dashboard(self.uid,'http://localhost')['states']['lab']
        self.fake.bad_lab=True;self.sync('lab');self.assertEqual(self.store.calendar(self.uid,'lab')['ics'],old['ics'])
        current=self.store.dashboard(self.uid,'http://localhost')['states']['lab'];self.assertEqual(current['last_success'],state['last_success']);self.assertEqual(current['state'],'error')
    def test_combined_lab_time_and_weekly_rule(self):
        self.sync('teaching','lab');calendar=self.store.calendar(self.uid,'combined');text=calendar['ics'].replace('\r\n ','')
        self.assertIn('RRULE:FREQ=WEEKLY;INTERVAL=2;COUNT=3',text)
        self.assertIn('DTSTART;TZID=Asia/Shanghai:20261013T210500',text);self.assertIn('DTEND;TZID=Asia/Shanghai:20261013T224500',text)
        self.assertEqual(text.count('TRIGGER;RELATED=START:-PT20M'),2);self.assertIn('测试实验室 测试教师',text)
    def test_scheduler_uses_stored_credentials_without_app_relogin(self):
        self.store.update_settings(self.uid,{'teaching':{'enabled':True,'interval_minutes':30},'lab':{'enabled':True,'interval_minutes':60}})
        with self.store.db() as c:c.execute('UPDATE sync_state SET next_run=? WHERE user_id=?',('2020-01-01T00:00:00+00:00',self.uid))
        self.manager.schedule_due();self.manager.pool.shutdown(wait=True)
        self.assertIn('app_fetch',self.fake.calls);self.assertIn('lab_fetch',self.fake.calls);self.assertNotIn('app_init',self.fake.calls)
        self.assertGreater(self.store.dashboard(self.uid,'http://localhost')['states']['teaching']['next_run'],now())
    def test_school_fetch_logs_are_separate_from_calendar_access(self):
        self.sync('lab');logs=self.store.dashboard(self.uid,'http://localhost')['logs'];school=[r for r in logs if r['category']=='school']
        self.assertEqual(len(school),2);self.assertIn('1页、1条实验',school[0]['message']);self.assertEqual(school[1]['event'],'SCHOOL_REQUEST_STARTED')
    def test_three_platform_tests_verify_full_timetable_without_publishing(self):
        self.store.save_secret(self.uid,{'token':'existing-test-token'})
        for platform in ('app','jw','lab'):self.manager.submit_platform(self.uid,platform,'test').result(timeout=5)
        self.assertEqual(self.fake.calls,['app_fetch','jw_fetch','lab_fetch'])
        dashboard=self.store.dashboard(self.uid,'http://localhost')
        for platform in ('app','jw','lab'):
            self.assertEqual(dashboard['platform_checks'][platform]['test']['state'],'ok')
            self.assertIn('课次',dashboard['platform_checks'][platform]['test']['message'])
            self.assertEqual(dashboard['platform_checks'][platform]['test']['identity_name'],'测试学生')
        self.assertIsNone(self.store.calendar(self.uid,'teaching'))
        self.assertIsNone(self.store.calendar(self.uid,'lab'))
    def test_app_test_never_logs_in_even_when_token_missing_or_expired(self):
        self.manager.submit_platform(self.uid,'app','test').result(timeout=5)
        self.assertEqual(self.fake.calls,[])
        self.assertEqual(self.store.dashboard(self.uid,'http://localhost')['platform_checks']['app']['test']['state'],'error')
        self.store.save_secret(self.uid,{'token':'expired-test-token'});self.fake.app_error='TOKEN_REQUIRED'
        self.manager.submit_platform(self.uid,'app','test').result(timeout=5)
        self.assertEqual(self.fake.calls,['app_fetch']);self.assertNotIn('app_init',self.fake.calls)
        self.assertIsNone(self.store.calendar(self.uid,'teaching'))
    def test_test_uses_unsaved_credentials_without_persisting_them(self):
        credentials={'student_id':'25110000000','jw_password':'Unsaved-test-password'}
        self.manager.submit_platform(self.uid,'jw','test',credentials).result(timeout=5)
        self.assertEqual(self.fake.credential_inputs[0]['jw_password'],'Unsaved-test-password')
        self.assertEqual(self.store.settings(self.uid)['credentials']['jw_password'],'Sensitive-jw-password')
        self.assertNotIn('Unsaved-test-password',json.dumps(self.store.dashboard(self.uid,'http://localhost')))
    def test_three_login_buttons_validate_identity_without_publishing_ics(self):
        for platform in ('app','jw','lab'):self.manager.submit_platform(self.uid,platform,'login').result(timeout=5)
        self.assertEqual(self.fake.calls,['app_init','jw_login','lab_login'])
        self.assertEqual(self.store.settings(self.uid)['credentials']['token'],'replacement-test-token')
        dashboard=self.store.dashboard(self.uid,'http://localhost')
        for platform in ('app','jw','lab'):
            self.assertEqual(dashboard['platform_checks'][platform]['login']['identity_name'],'测试学生')
            self.assertEqual(dashboard['platform_checks'][platform]['login']['state'],'ok')
        self.assertEqual(dashboard['states']['teaching']['state'],'idle');self.assertEqual(dashboard['states']['lab']['state'],'idle')
        self.assertEqual(dashboard['calendars'],{})
    def test_platform_login_failure_does_not_change_timetable_or_failover(self):
        self.sync('lab');previous=self.store.calendar(self.uid,'lab')['ics'];self.fake.calls=[];self.fake.lab_error='LOGIN_FAILED'
        self.manager.submit_platform(self.uid,'lab','login').result(timeout=5)
        dashboard=self.store.dashboard(self.uid,'http://localhost')
        self.assertEqual(self.fake.calls,['lab_login']);self.assertEqual(dashboard['platform_checks']['lab']['login']['state'],'error')
        self.assertEqual(self.store.calendar(self.uid,'lab')['ics'],previous);self.assertEqual(dashboard['states']['lab']['state'],'ok')
    def test_editing_credentials_invalidates_previous_login_verification(self):
        self.manager.submit_platform(self.uid,'jw','login').result(timeout=5)
        self.store.update_settings(self.uid,{'jw_password':'New-sensitive-password'})
        self.assertEqual(self.store.dashboard(self.uid,'http://localhost')['platform_checks']['jw'],{})
    def test_link_rotation_and_user_isolation(self):
        self.sync('lab');link=self.store.links(self.uid,'http://localhost')['lab'];token=link.split('/')[-2]
        other=self.store.create_user('another-user',PASSWORD);self.assertIsNone(self.store.calendar(other['id'],'lab'))
        self.assertIsNotNone(self.store.calendar_for_token(token,'lab'));self.assertIsNone(self.store.calendar_for_token(token,'teaching'))
        self.store.rotate(self.uid,'lab');self.assertIsNone(self.store.calendar_for_token(token,'lab'))
    def test_persistence_survives_store_restart(self):
        self.sync('lab');old_links=self.store.links(self.uid,'http://localhost');other=Store(self.temp.name)
        self.assertEqual(other.settings(self.uid)['credentials']['campus_password'],'Sensitive-campus-password')
        self.assertEqual(other.links(self.uid,'http://localhost'),old_links);self.assertIsNotNone(other.calendar(self.uid,'lab'))
    def test_last_admin_cannot_be_disabled_or_demoted(self):
        admin=self.store.create_user('admin-user',PASSWORD,'admin')
        with self.assertRaises(ValueError):self.store.admin_update(admin['id'],admin['id'],{'disabled':True})
        with self.assertRaises(ValueError):self.store.admin_update(admin['id'],admin['id'],{'role':'user'})
    def test_http_auth_csrf_admin_and_delivery_etag(self):
        self.sync('lab');server=CalendarServer(('127.0.0.1',0),self.store,self.manager)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='http://127.0.0.1:'+str(server.server_port)
        def request(path,method='GET',data=None,headers=None):
            body=json.dumps(data).encode() if data is not None else None
            return urlopen(Request(base+path,data=body,method=method,headers={'Content-Type':'application/json',**(headers or {})}),timeout=5)
        try:
            with self.assertRaises(HTTPError) as unauthorized:request('/api/dashboard')
            self.assertEqual(unauthorized.exception.code,401)
            with request('/api/login','POST',{'username':'tester','password':PASSWORD}) as login:
                cookie=login.headers['Set-Cookie'].split(';')[0];csrf=json.load(login)['csrf']
                self.assertIn('HttpOnly',login.headers['Set-Cookie'])
            with self.assertRaises(HTTPError) as forbidden:request('/api/settings','PUT',{'mode':'jw'},{'Cookie':cookie})
            self.assertEqual(forbidden.exception.code,403)
            with self.assertRaises(HTTPError) as admin_forbidden:request('/api/admin/users',headers={'Cookie':cookie})
            self.assertEqual(admin_forbidden.exception.code,403)
            with request('/api/settings','PUT',{'mode':'jw'},{'Cookie':cookie,'X-CSRF-Token':csrf}) as response:self.assertEqual(json.load(response)['mode'],'jw')
            with self.assertRaises(HTTPError) as bad_origin:request('/api/settings','PUT',{'mode':'app'},{'Cookie':cookie,'X-CSRF-Token':csrf,'Origin':'https://evil.example'})
            self.assertEqual(bad_origin.exception.code,403)
            link=self.store.links(self.uid,base)['lab'];path=link[len(base):]
            with request(path) as response:etag=response.headers['ETag'];self.assertIn(b'BEGIN:VCALENDAR',response.read())
            with self.assertRaises(HTTPError) as not_modified:request(path,headers={'If-None-Match':etag})
            self.assertEqual(not_modified.exception.code,304)
            logs=self.store.dashboard(self.uid,base)['logs'];self.assertEqual(sum(r['category']=='delivery' for r in logs),2)
            with self.assertRaises(HTTPError) as denied:request('/../../core.py')
            self.assertEqual(denied.exception.code,404)
            with self.assertRaises(HTTPError) as missing_ack:request('/api/platforms/app/login','POST',{}, {'Cookie':cookie,'X-CSRF-Token':csrf})
            self.assertEqual(missing_ack.exception.code,400)
            with self.assertRaises(HTTPError) as no_csrf:request('/api/platforms/jw/test','POST',{}, {'Cookie':cookie})
            self.assertEqual(no_csrf.exception.code,403)
            with request('/api/platforms/jw/login','POST',{}, {'Cookie':cookie,'X-CSRF-Token':csrf}) as accepted:self.assertEqual(accepted.status,202)
            self.manager.pool.shutdown(wait=True)
            self.assertEqual(self.store.dashboard(self.uid,base)['platform_checks']['jw']['login']['state'],'ok')
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

if __name__=='__main__':unittest.main()
