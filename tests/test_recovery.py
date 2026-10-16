import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen

from core import Store
from recovery import FAILURE,prepare_recovery
from server import CalendarServer
from sync import SyncManager

PASSWORD='Original-test-password-42'
NEW_PASSWORD='Replacement-test-password-56'
ANSWERS=[{'question':'first_pet','answer':'First Pet Value'},{'question':'first_school','answer':'First School Value'}]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.user=self.store.create_user('recovery-user',PASSWORD,recovery=ANSWERS)
    def tearDown(self):self.temp.cleanup()
    def record(self,uid=None):
        with self.store.db() as c:
            row=c.execute('SELECT * FROM account_recovery WHERE user_id=?',(uid or self.user['id'],)).fetchone()
            return dict(row) if row else None
    def test_answers_are_salted_hashes_and_never_public(self):
        other=self.store.create_user('recovery-other',PASSWORD,recovery=ANSWERS)
        stored=self.record();self.assertNotEqual(stored['answer_hashes'],self.record(other['id'])['answer_hashes'])
        self.assertNotIn('First Pet Value',json.dumps(stored))
        public=json.dumps(self.store.dashboard(self.user['id'],'http://localhost'))
        self.assertNotIn('answer_hashes',public);self.assertNotIn(stored['answer_hashes'],public)
        self.assertTrue(self.store.public_settings(self.user['id'])['recovery_enabled'])
    def test_optional_registration_and_invalid_recovery_are_atomic(self):
        plain=self.store.create_user('without-recovery',PASSWORD)
        self.assertFalse(self.store.public_settings(plain['id'])['recovery_enabled'])
        for invalid in [[],ANSWERS[:1],[ANSWERS[0],ANSWERS[0]],[{'question':'<script>','answer':'valid'},ANSWERS[1]],[{'question':'first_pet','answer':' '},ANSWERS[1]],'bad']:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.store.create_user('invalid-recovery',PASSWORD,recovery=invalid)
        with self.store.db() as c:self.assertIsNone(c.execute('SELECT 1 FROM users WHERE username=?',('invalid-recovery',)).fetchone())
    def test_correct_answers_normalize_and_reset_only_target_account(self):
        user=self.user;other=self.store.create_user('other-password',PASSWORD)
        tokens=[self.store.session(user['id'])[0] for _ in range(2)];other_token=self.store.session(other['id'])[0]
        self.store.update_settings(user['id'],{'student_id':'25110000000','campus_password':'School-secret-unchanged'})
        links=self.store.links(user['id'],'http://localhost');settings=self.store.settings(user['id'])
        normalized=[{'question':'first_pet','answer':'  ＦＩＲＳＴ   PET value '},ANSWERS[1]]
        self.store.reset_with_recovery('RECOVERY-USER',normalized,NEW_PASSWORD)
        self.assertEqual(self.store.login(user['username'],NEW_PASSWORD)['id'],user['id'])
        with self.assertRaises(ValueError):self.store.login(user['username'],PASSWORD)
        for token in tokens:self.assertIsNone(self.store.authenticate(token))
        self.assertIsNotNone(self.store.authenticate(other_token))
        self.assertEqual(self.store.settings(user['id']),settings);self.assertEqual(self.store.links(user['id'],'http://localhost'),links)
        self.assertEqual(self.store.login(other['username'],PASSWORD)['id'],other['id'])
    def test_wrong_missing_or_reordered_answers_never_change_password_or_session(self):
        token,_=self.store.session(self.user['id'])
        for bad in [None,[],[ANSWERS[0]],list(reversed(ANSWERS)),[ANSWERS[0],{'question':'first_school','answer':'wrong answer'}],[{},{}],['not-object',None]]:
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,FAILURE):self.store.reset_with_recovery(self.user['username'],bad,NEW_PASSWORD)
            self.assertIsNotNone(self.store.authenticate(token))
        self.assertEqual(self.store.login(self.user['username'],PASSWORD)['id'],self.user['id'])
    def test_unknown_disabled_unconfigured_and_admin_accounts_cannot_reset(self):
        disabled=self.store.create_user('disabled-user',PASSWORD,recovery=ANSWERS)
        plain=self.store.create_user('plain-user',PASSWORD)
        admin=self.store.create_user('admin-user',PASSWORD,'admin',recovery=ANSWERS)
        with self.store.db() as c:c.execute('UPDATE users SET disabled=1 WHERE id=?',(disabled['id'],))
        for name in ['missing-user',disabled['username'],plain['username'],admin['username']]:
            with self.subTest(username=name),self.assertRaisesRegex(ValueError,FAILURE):self.store.reset_with_recovery(name,ANSWERS,NEW_PASSWORD)
            questions=self.store.recovery_questions(name)
            self.assertEqual(len(questions),2);self.assertEqual(set(questions[0]),{'id','label'})
        self.assertEqual(self.store.recovery_questions('missing-user'),self.store.recovery_questions('missing-user'))
        self.assertIsNone(self.record(admin['id']))
    def test_existing_user_can_replace_questions_only_with_current_password(self):
        before=self.record()
        replacement=[{'question':'birth_city','answer':'Test City'},ANSWERS[1]]
        with self.assertRaises(ValueError):self.store.set_recovery(self.user['id'],'wrong-password',replacement)
        self.assertEqual(self.record(),before)
        self.store.set_recovery(self.user['id'],PASSWORD,replacement)
        with self.assertRaisesRegex(ValueError,FAILURE):self.store.reset_with_recovery(self.user['username'],ANSWERS,NEW_PASSWORD)
        self.store.reset_with_recovery(self.user['username'],replacement,NEW_PASSWORD)
    def test_invalid_new_password_does_not_revoke_sessions_and_restart_preserves_recovery(self):
        token,_=self.store.session(self.user['id'])
        with self.assertRaises(ValueError):self.store.reset_with_recovery(self.user['username'],ANSWERS,'short')
        self.assertIsNotNone(self.store.authenticate(token))
        self.store=Store(self.temp.name)
        self.store.reset_with_recovery(self.user['username'],ANSWERS,NEW_PASSWORD)
        with self.store.db() as c:logs=[dict(row) for row in c.execute('SELECT * FROM logs')]
        serialized=json.dumps(logs)
        for secret in [PASSWORD,NEW_PASSWORD,*[entry['answer'] for entry in ANSWERS]]:self.assertNotIn(secret,serialized)


class RecoveryHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.manager=SyncManager(self.store);self.server=CalendarServer(('127.0.0.1',0),self.store,self.manager)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.manager.close();self.thread.join(timeout=3);self.temp.cleanup()
    def call(self,path,data,method='POST',headers=None):
        request=Request(self.base+path,data=json.dumps(data).encode(),method=method,headers={'Content-Type':'application/json',**(headers or {})})
        try:
            with urlopen(request) as response:return response.status,json.load(response)
        except HTTPError as error:return error.code,json.load(error)
    def test_register_questions_reset_login_and_metadata(self):
        status,result=self.call('/api/register',{'username':'new-recovery','password':PASSWORD,'consent':True,'recovery':ANSWERS})
        self.assertEqual(status,200);self.assertNotIn('recovery',result)
        status,result=self.call('/api/recovery/questions',{'username':'new-recovery'})
        self.assertEqual(status,200);self.assertEqual([q['id'] for q in result['questions']],['first_pet','first_school'])
        self.server.registration=False
        self.assertEqual(self.call('/api/recovery/reset',{'username':'new-recovery','answers':ANSWERS,'new_password':NEW_PASSWORD})[0],200)
        self.assertEqual(self.call('/api/login',{'username':'new-recovery','password':NEW_PASSWORD})[0],200)
        with urlopen(self.base+'/api/bootstrap') as response:self.assertEqual(len(json.load(response)['recovery_questions']),6)
    def test_setting_requires_session_csrf_and_current_password(self):
        user=self.store.create_user('settings-recovery',PASSWORD);token,csrf=self.store.session(user['id'])
        body={'current_password':PASSWORD,'recovery':ANSWERS};path='/api/account/recovery'
        self.assertEqual(self.call(path,body,'PUT')[0],401)
        headers={'Cookie':'koma_session='+token}
        self.assertEqual(self.call(path,body,'PUT',headers)[0],403)
        headers['X-CSRF-Token']=csrf
        self.assertEqual(self.call(path,{**body,'current_password':'wrong-password'},'PUT',headers)[0],400)
        self.assertEqual(self.call(path,body,'PUT',headers)[0],200)
    def test_foreign_origin_and_brute_force_rejected_even_with_forged_ip_headers(self):
        user=self.store.create_user('limited-recovery',PASSWORD,recovery=ANSWERS)
        body={'username':user['username'],'answers':[ANSWERS[0],{'question':'first_school','answer':'wrong answer'}],'new_password':NEW_PASSWORD}
        self.assertEqual(self.call('/api/recovery/reset',body,headers={'Origin':'https://evil.example'})[0],403)
        for attempt in range(5):
            status,result=self.call('/api/recovery/reset',body,headers={'CF-Connecting-IP':f'2001:db8::{attempt+1}'})
            self.assertEqual(status,400);self.assertEqual(result['error'],FAILURE)
        body['username']=user['username'].upper();body['answers']=ANSWERS
        self.assertEqual(self.call('/api/recovery/reset',body)[0],429)
        self.assertEqual(self.store.login(user['username'],PASSWORD)['id'],user['id'])


if __name__=='__main__':unittest.main()
