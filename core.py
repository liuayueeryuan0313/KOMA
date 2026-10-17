"""Persistent accounts, encrypted school credentials and isolated calendar storage."""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from recovery import QUESTIONS,FAILURE,DUMMY_HASH,prepare_recovery,public_questions,check_answers
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from school_profiles import prepare_school_config,prepare_clock_config,school_changed
from adapters.scripts.compile_calendar import compile_calendar,reminder_settings

ROOT=Path(__file__).resolve().parent
KINDS=('teaching','lab','combined')
DISCLAIMER_VERSION='2026-10-16'
DISCLAIMER='课间是由安稳开发的非学校官方课表整理工具。仅使用本人有权访问的学校账户；课程、调课、实验安排以学校公布的信息为准。同步可能受认证、网络或接口变化影响，请核对重要安排。本工具不保证日历客户端的刷新时效，也不替代学校通知。保存凭据用于本人授权的同步，可随时删除；请勿向他人分享账户或私密订阅链接。'

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def later(minutes):return (datetime.now(timezone.utc)+timedelta(minutes=minutes)).isoformat(timespec='seconds')
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def json_text(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
def occurrence_id(row):return digest(json_text(row))
def password_hash(password):
    if not isinstance(password,str) or not 10<=len(password)<=256:raise ValueError('站内密码须为10–256个字符')
    salt=secrets.token_bytes(16)
    hashed=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,maxmem=64*1024*1024)
    return base64.b64encode(salt+hashed).decode()
def password_ok(password,stored):
    try:
        if not isinstance(password,str) or len(password)>256:return False
        blob=base64.b64decode(stored)
        actual=hashlib.scrypt(password.encode(),salt=blob[:16],n=16384,r=8,p=1,maxmem=64*1024*1024)
        return hmac.compare_digest(actual,blob[16:])
    except (ValueError,TypeError):return False
def valid_username(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_\-.\u4e00-\u9fff]{3,32}',value):raise ValueError('用户名须为3–32位字母、数字、汉字或 _ . -')
    return value

class Store:
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.path=self.directory/'komama.sqlite3';key_path=self.directory/'master.key'
        if not key_path.exists():
            if self.path.exists():raise RuntimeError('Existing database requires its original master.key')
            descriptor=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(descriptor,'wb') as file:file.write(AESGCM.generate_key(bit_length=256))
        self.cipher=AESGCM(key_path.read_bytes())
        with self.db() as connection:
            connection.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT NOT NULL UNIQUE COLLATE NOCASE,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','user')),disabled INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,consent_version TEXT NOT NULL,student_name TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS avatars(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,image BLOB NOT NULL,version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS account_recovery(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,questions TEXT NOT NULL,answer_hashes TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS settings(user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,secret TEXT NOT NULL,config TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'auto');
            CREATE TABLE IF NOT EXISTS sync_state(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL CHECK(kind IN ('teaching','lab')),enabled INTEGER NOT NULL DEFAULT 0,interval_minutes INTEGER NOT NULL DEFAULT 360,next_run TEXT,last_attempt TEXT,last_success TEXT,state TEXT NOT NULL DEFAULT 'idle',active_source TEXT,warning TEXT NOT NULL DEFAULT '',identity_name TEXT NOT NULL DEFAULT '',identity_id TEXT NOT NULL DEFAULT '',PRIMARY KEY(user_id,kind));
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,csrf TEXT NOT NULL,expires TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calendars(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,ics TEXT NOT NULL,etag TEXT NOT NULL,snapshot TEXT NOT NULL,normalized TEXT NOT NULL,metrics TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(user_id,kind));
            CREATE TABLE IF NOT EXISTS school_sources(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,term TEXT NOT NULL,snapshot TEXT NOT NULL,normalized TEXT NOT NULL,PRIMARY KEY(user_id,kind,term));
            CREATE TABLE IF NOT EXISTS school_occurrences(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,term TEXT NOT NULL,identifier TEXT NOT NULL,row TEXT NOT NULL,active INTEGER NOT NULL,PRIMARY KEY(user_id,kind,term,identifier));
            CREATE TABLE IF NOT EXISTS manual_occurrences(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,term TEXT NOT NULL,identifier TEXT NOT NULL,mode TEXT NOT NULL CHECK(mode IN ('create','override')),baseline TEXT NOT NULL,fields TEXT NOT NULL,PRIMARY KEY(user_id,kind,term,identifier));
            CREATE TABLE IF NOT EXISTS deleted_occurrences(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,term TEXT NOT NULL,identifier TEXT NOT NULL,deleted_at TEXT NOT NULL,PRIMARY KEY(user_id,kind,term,identifier));
            CREATE TABLE IF NOT EXISTS links(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,token_secret TEXT NOT NULL,PRIMARY KEY(user_id,kind));
            CREATE TABLE IF NOT EXISTS logs(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,kind TEXT NOT NULL,category TEXT NOT NULL,level TEXT NOT NULL,event TEXT NOT NULL,message TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS logs_user ON logs(user_id,id DESC);
            CREATE TABLE IF NOT EXISTS rate_limits(bucket TEXT PRIMARY KEY,attempts INTEGER NOT NULL,reset_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS platform_checks(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,platform TEXT NOT NULL,action TEXT NOT NULL,state TEXT NOT NULL,message TEXT NOT NULL,checked_at TEXT NOT NULL,identity_name TEXT NOT NULL DEFAULT '',identity_id TEXT NOT NULL DEFAULT '',PRIMARY KEY(user_id,platform,action));
            ''')
            connection.execute("UPDATE sync_state SET state='error',warning='服务重启中断了上次任务；已保留最近成功课表' WHERE state IN ('running','queued')")
            connection.execute("UPDATE platform_checks SET state='error',message='服务重启中断了检查，请重新操作' WHERE state='running'")
        from calendar_layers import migrate_legacy
        migrate_legacy(self)
        self.setup_path=self.directory/'setup-token'
        if not self.has_admin() and not self.setup_path.exists():
            self.setup_path.write_text(secrets.token_urlsafe(24),encoding='utf-8');self.setup_path.chmod(0o600)

    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path,timeout=20)
        connection.row_factory=sqlite3.Row;connection.execute('PRAGMA foreign_keys=ON');connection.execute('PRAGMA busy_timeout=20000')
        try:yield connection;connection.commit()
        except Exception:connection.rollback();raise
        finally:connection.close()

    def encrypt(self,value,context):
        nonce=secrets.token_bytes(12)
        return base64.b64encode(nonce+self.cipher.encrypt(nonce,json_text(value).encode(),context.encode())).decode()
    def decrypt(self,value,context):
        blob=base64.b64decode(value);return json.loads(self.cipher.decrypt(blob[:12],blob[12:],context.encode()))
    def has_admin(self):
        with self.db() as c:return c.execute("SELECT 1 FROM users WHERE role='admin' AND disabled=0").fetchone() is not None
    def create_user(self,username,password,role='user',setup_token=None,recovery=None):
        valid_username(username);hashed=password_hash(password);identifier=secrets.token_hex(16)
        recovery_data=prepare_recovery(recovery) if role=='user' else None
        config=json.loads((ROOT/'adapters/config.json').read_text(encoding='utf-8'))
        config.update(calendar_id='komama:'+identifier,calendar_name='我的课表',jw_semester_code='3',reminder_enabled=True,reminder_minutes=20)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            if role=='admin':
                if c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone():raise ValueError('管理员已初始化')
                if setup_token is not None:
                    if not self.setup_path.exists() or not hmac.compare_digest(setup_token,self.setup_path.read_text().strip()):raise ValueError('一次性设置码无效')
            elif role!='user':raise ValueError('无效权限组')
            try:c.execute('INSERT INTO users(id,username,password_hash,role,created_at,consent_version) VALUES(?,?,?,?,?,?)',(identifier,username,hashed,role,now(),DISCLAIMER_VERSION))
            except sqlite3.IntegrityError:raise ValueError('用户名已存在') from None
            if recovery_data:c.execute('INSERT INTO account_recovery VALUES(?,?,?)',(identifier,json_text(recovery_data[0]),json_text(recovery_data[1])))
            c.execute('INSERT INTO settings(user_id,secret,config) VALUES(?,?,?)',(identifier,self.encrypt({},identifier),json_text(config)))
            for kind in ('teaching','lab'):c.execute('INSERT INTO sync_state(user_id,kind) VALUES(?,?)',(identifier,kind))
            for kind in KINDS:self._rotate(c,identifier,kind)
        if role=='admin' and self.setup_path.exists():self.setup_path.unlink()
        return self.user(identifier)
    def user(self,identifier):
        with self.db() as c:
            row=c.execute('SELECT users.id,username,role,disabled,created_at,student_name,avatars.version AS avatar_version FROM users LEFT JOIN avatars ON avatars.user_id=users.id WHERE users.id=?',(identifier,)).fetchone()
            return dict(row) if row else None
    def debug_source_ip(self,user_id):
        with self.db() as c:row=c.execute('SELECT config FROM settings WHERE user_id=?',(user_id,)).fetchone()
        return bool(json.loads(row['config']).get('debug_source_ip',False))
    def set_debug_source_ip(self,user_id,enabled):
        if not isinstance(enabled,bool):raise ValueError('请选择有效的调试选项')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT config FROM settings WHERE user_id=?',(user_id,)).fetchone()
            config=json.loads(row['config']);config['debug_source_ip']=enabled
            c.execute('UPDATE settings SET config=? WHERE user_id=?',(json_text(config),user_id))
    def avatar(self,user_id):
        with self.db() as c:row=c.execute('SELECT image FROM avatars WHERE user_id=?',(user_id,)).fetchone()
        return bytes(row['image']) if row else None
    def save_avatar(self,user_id,value):
        from avatars import decode_avatar
        image=decode_avatar(value) if value is not None else None
        with self.db() as c:
            if image is None:c.execute('DELETE FROM avatars WHERE user_id=?',(user_id,))
            else:c.execute('INSERT OR REPLACE INTO avatars VALUES(?,?,?)',(user_id,image,hashlib.sha256(image).hexdigest()))
        return self.user(user_id)
    def login(self,username,password):
        with self.db() as c:row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        # Run the same work for unknown accounts to avoid a cheap timing distinction.
        stored=row['password_hash'] if row else base64.b64encode(b'0'*80).decode()
        if not password_ok(password,stored) or not row or row['disabled']:raise ValueError('用户名或密码错误')
        return self.user(row['id'])
    def recovery_questions(self,username):
        valid_username(username)
        with self.db() as c:
            row=c.execute("SELECT r.questions FROM account_recovery r JOIN users u ON u.id=r.user_id WHERE u.username=? AND u.role='user' AND u.disabled=0",(username,)).fetchone()
        return public_questions(username,json.loads(row['questions']) if row else None)
    def set_recovery(self,user_id,current_password,entries):
        prepared=prepare_recovery(entries)
        if not prepared:raise ValueError('请填写两道密保问题和答案')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            user=c.execute("SELECT * FROM users WHERE id=? AND role='user' AND disabled=0",(user_id,)).fetchone()
            if not user or not password_ok(current_password,user['password_hash']):raise ValueError('当前密码不正确，或账户不支持密保')
            c.execute('INSERT OR REPLACE INTO account_recovery VALUES(?,?,?)',(user_id,json_text(prepared[0]),json_text(prepared[1])))
        self.log(user_id,'account','RECOVERY_CONFIGURED','已设置站内账户密保',category='account')
    def reset_with_recovery(self,username,entries,new_password):
        valid_username(username)
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute("SELECT u.id,r.questions,r.answer_hashes FROM users u JOIN account_recovery r ON r.user_id=u.id WHERE u.username=? AND u.role='user' AND u.disabled=0",(username,)).fetchone()
            questions=json.loads(row['questions']) if row else [q['id'] for q in public_questions(username)]
            hashes=json.loads(row['answer_hashes']) if row else [DUMMY_HASH,DUMMY_HASH]
            verified=check_answers(questions,hashes,entries)
            if not verified or not row:raise ValueError(FAILURE)
            hashed=password_hash(new_password)
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(hashed,row['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
        self.log(row['id'],'account','PASSWORD_RECOVERED','已通过密保重设站内密码，旧登录会话已失效',category='account')
    def session(self,user_id):
        token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
        with self.db() as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(now(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(digest(token),user_id,csrf,later(7*24*60)))
        return token,csrf
    def authenticate(self,token):
        with self.db() as c:
            row=c.execute('SELECT users.id,users.username,users.role,users.student_name,sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>? AND users.disabled=0',(digest(token),now())).fetchone()
            return dict(row) if row else None
    def logout(self,token):
        with self.db() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(digest(token),))
    def settings(self,user_id):
        with self.db() as c:row=c.execute('SELECT * FROM settings WHERE user_id=?',(user_id,)).fetchone()
        return {'credentials':self.decrypt(row['secret'],user_id),'config':json.loads(row['config']),'mode':row['mode']}
    def public_settings(self,user_id):
        settings=self.settings(user_id);creds=settings.pop('credentials')
        settings['config'].setdefault('reminder_enabled',True);settings['config'].setdefault('reminder_minutes',20)
        settings.update(student_id=creds.get('student_id',''),has_campus_password=bool(creds.get('campus_password')),has_jw_password=bool(creds.get('jw_password')),has_app_token=bool(creds.get('token')),app_token_invalid=bool(creds.get('token_invalid')))
        with self.db() as c:settings['recovery_enabled']=c.execute('SELECT 1 FROM account_recovery WHERE user_id=?',(user_id,)).fetchone() is not None
        return settings
    def update_settings(self,user_id,data):
        old=self.settings(user_id);creds=old['credentials'];config=prepare_school_config(old['config'],data);mode=data.get('mode',old['mode'])
        if mode not in ('auto','app','jw'):raise ValueError('无效教学课表来源')
        student_id=str(data.get('student_id',creds.get('student_id',''))).strip()
        if student_id and not re.fullmatch(r'[A-Za-z0-9]{5,32}',student_id):raise ValueError('请填写正确学号')
        changed=student_id!=creds.get('student_id','') or school_changed(old['config'],config)
        if changed:
            creds={};config['course_details']={}
        if data.get('term',config['term'])!=config['term']:config['course_details']={}
        creds['student_id']=student_id
        for field in ('campus_password','jw_password'):
            value=data.get(field)
            if value:
                if not isinstance(value,str) or len(value)>256:raise ValueError('密码长度无效')
                creds[field]=value
        if data.get('app_token'):
            value=data['app_token']
            if not isinstance(value,str) or len(value)>4096:raise ValueError('token长度无效')
            creds['token']=value.strip()
            creds['token_invalid']=False
        if data.get('clear_credentials'):creds={'student_id':student_id}
        for field in ('term','week1_monday','maxWeekNumber','jw_semester_code'):
            if field in data:config[field]=data[field]
        config=prepare_clock_config(config,data)
        if not re.fullmatch(r'\d{4}-\d{4}-[12]',str(config['term'])):raise ValueError('学期格式应为2026-2027-1')
        first=datetime.fromisoformat(str(config['week1_monday']))
        if first.weekday()!=0:raise ValueError('第一周日期必须是星期一')
        config['maxWeekNumber']=int(config['maxWeekNumber'])
        if not 1<=config['maxWeekNumber']<=53:raise ValueError('学期周数须为1–53')
        if not re.fullmatch(r'\d{1,2}',str(config['jw_semester_code'])):raise ValueError('教务学期编码无效')
        for field in ('reminder_enabled','reminder_minutes'):
            if field in data:config[field]=data[field]
        reminder_changed=reminder_settings(old['config'])!=reminder_settings(config)
        plans=[]
        for kind in ('teaching','lab'):
            plan=data.get(kind,{})
            if plan:
                interval=int(plan.get('interval_minutes',360));enabled=bool(plan.get('enabled',False))
                if not 15<=interval<=10080:raise ValueError('更新间隔须为15分钟至7天')
                plans.append((enabled,interval,later(interval) if enabled else None,user_id,kind))
        with self.db() as c:
            c.execute('UPDATE settings SET secret=?,config=?,mode=? WHERE user_id=?',(self.encrypt(creds,user_id),json_text(config),mode,user_id))
            if data.get('campus_password') or data.get('clear_credentials'):c.execute("DELETE FROM platform_checks WHERE user_id=? AND platform IN ('app','lab') AND action='login'",(user_id,))
            if data.get('jw_password') or data.get('clear_credentials'):c.execute("DELETE FROM platform_checks WHERE user_id=? AND platform='jw' AND action='login'",(user_id,))
            if data.get('app_token'):c.execute("DELETE FROM platform_checks WHERE user_id=? AND platform='app' AND action='login'",(user_id,))
            for values in plans:c.execute('UPDATE sync_state SET enabled=?,interval_minutes=?,next_run=? WHERE user_id=? AND kind=?',values)
            if changed:
                c.execute('DELETE FROM platform_checks WHERE user_id=?',(user_id,))
                c.execute('DELETE FROM calendars WHERE user_id=?',(user_id,))
                for table in ('school_sources','school_occurrences','manual_occurrences','deleted_occurrences'):c.execute('DELETE FROM '+table+' WHERE user_id=?',(user_id,))
                c.execute("UPDATE users SET student_name='' WHERE id=?",(user_id,))
                c.execute("UPDATE sync_state SET last_attempt=NULL,last_success=NULL,state='idle',active_source=NULL,warning='',identity_name='',identity_id='' WHERE user_id=?",(user_id,))
                for kind in KINDS:self._rotate(c,user_id,kind)
            elif old['config']['term']!=config['term']:
                c.execute('DELETE FROM calendars WHERE user_id=?',(user_id,))
                from calendar_layers import rebuild
                rebuild(c,user_id,config)
            elif reminder_changed:
                # Rewrite every existing feed atomically from saved occurrences;
                # changing reminders never needs another school fetch.
                calendars=c.execute('SELECT kind,normalized,metrics FROM calendars WHERE user_id=?',(user_id,)).fetchall()
                for calendar in calendars:
                    ics,metrics=compile_calendar(json.loads(calendar['normalized']),config)
                    metrics={**json.loads(calendar['metrics']),**metrics}
                    c.execute('UPDATE calendars SET ics=?,etag=?,metrics=?,updated_at=? WHERE user_id=? AND kind=?',(ics,digest(ics),json_text(metrics),now(),user_id,calendar['kind']))
        self.log(user_id,'account','SETTINGS_SAVED','账户与同步设置已保存')
        return self.public_settings(user_id)
    def save_secret(self,user_id,updates):
        settings=self.settings(user_id);settings['credentials'].update(updates)
        if updates.get('token'):settings['credentials']['token_invalid']=False
        with self.db() as c:c.execute('UPDATE settings SET secret=? WHERE user_id=?',(self.encrypt(settings['credentials'],user_id),user_id))
    def platform_check(self,user_id,platform,action,state,message,identity=None):
        identity=identity or {}
        with self.db() as c:c.execute('INSERT OR REPLACE INTO platform_checks(user_id,platform,action,state,message,checked_at,identity_name,identity_id) VALUES(?,?,?,?,?,?,?,?)',(user_id,platform,action,state,message[:500],now(),str(identity.get('name',''))[:100],str(identity.get('studentId',''))[:40]))
    def save_teacher_cache(self,user_id,rows):
        settings=self.settings(user_id);details=settings['config'].setdefault('course_details',{})
        for row in rows:
            if row.get('teacher'):details[str(row['kcdm'])]={'teacher':row['teacher']}
        with self.db() as c:c.execute('UPDATE settings SET config=? WHERE user_id=?',(json_text(settings['config']),user_id))
    def log(self,user_id,kind,event,message,level='info',category='sync'):
        # Callers use fixed descriptions, never raw exceptions or upstream response bodies.
        with self.db() as c:
            c.execute('INSERT INTO logs(user_id,kind,category,level,event,message,created_at) VALUES(?,?,?,?,?,?,?)',(user_id,kind,category,level,event,message[:500],now()))
            c.execute('DELETE FROM logs WHERE user_id=? AND id NOT IN (SELECT id FROM logs WHERE user_id=? ORDER BY id DESC LIMIT 1000)',(user_id,user_id))
    def _rotate(self,c,user_id,kind):
        token=secrets.token_urlsafe(32)
        c.execute('INSERT OR REPLACE INTO links VALUES(?,?,?,?)',(user_id,kind,digest(token),self.encrypt(token,user_id+':'+kind)))
    def rotate(self,user_id,kind):
        if kind not in KINDS:raise ValueError('无效订阅类型')
        with self.db() as c:self._rotate(c,user_id,kind)
        self.log(user_id,kind,'LINK_ROTATED','私密订阅链接已更换，旧链接失效',category='delivery')
    def links(self,user_id,public_url):
        with self.db() as c:rows=c.execute('SELECT * FROM links WHERE user_id=?',(user_id,)).fetchall()
        return {r['kind']:public_url.rstrip('/')+'/cal/'+self.decrypt(r['token_secret'],user_id+':'+r['kind'])+'/'+r['kind']+'.ics' for r in rows}
    def calendar(self,user_id,kind):
        with self.db() as c:
            row=c.execute('SELECT * FROM calendars WHERE user_id=? AND kind=?',(user_id,kind)).fetchone();return dict(row) if row else None
    def put_calendar(self,user_id,kind,snapshot,normalized,ics,metrics):
        if kind in ('teaching','lab'):
            from calendar_layers import publish_school
            return publish_school(self,user_id,kind,snapshot,normalized)
        with self.db() as c:c.execute('INSERT OR REPLACE INTO calendars VALUES(?,?,?,?,?,?,?,?)',(user_id,kind,ics,digest(ics),json_text(snapshot),json_text(normalized),json_text(metrics),now()))
    def calendar_for_token(self,token,kind):
        with self.db() as c:
            row=c.execute('SELECT calendars.* FROM links JOIN users ON users.id=links.user_id JOIN calendars ON calendars.user_id=links.user_id AND calendars.kind=links.kind WHERE links.token_hash=? AND links.kind=? AND users.disabled=0',(digest(token),kind)).fetchone()
            return dict(row) if row else None
    def dashboard(self,user_id,public_url):
        user=self.user(user_id);settings=self.public_settings(user_id)
        with self.db() as c:
            states={r['kind']:dict(r) for r in c.execute('SELECT * FROM sync_state WHERE user_id=?',(user_id,))}
            calendars={r['kind']:{'updated_at':r['updated_at'],**json.loads(r['metrics'])} for r in c.execute('SELECT * FROM calendars WHERE user_id=?',(user_id,))}
            logs=[dict(r) for r in c.execute('SELECT id,kind,category,level,event,message,created_at FROM logs WHERE user_id=? ORDER BY id DESC LIMIT 100',(user_id,))]
            checks={platform:{} for platform in ('app','jw','lab')}
            for row in c.execute('SELECT platform,action,state,message,checked_at,identity_name,identity_id FROM platform_checks WHERE user_id=?',(user_id,)):checks[row['platform']][row['action']]=dict(row)
        occurrences=[]
        for kind in ('teaching','lab'):
            cal=self.calendar(user_id,kind)
            if cal:occurrences.extend([{**r,'kind':kind,'occurrenceId':r.get('occurrenceId') or occurrence_id(r)} for r in json.loads(cal['normalized'])['occurrences']])
        occurrences.sort(key=lambda r:(r['startLocal'],r['courseId']))
        return {'user':user,'settings':settings,'states':states,'calendars':calendars,'links':self.links(user_id,public_url),'occurrences':occurrences,'logs':logs,'platform_checks':checks}
    def admin_users(self):
        with self.db() as c:
            rows=c.execute('SELECT id,username,role,disabled,student_name,created_at FROM users ORDER BY created_at').fetchall()
        return [dict(r) for r in rows]
    def admin_update(self,actor,target,data):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM users WHERE id=?',(target,)).fetchone()
            if not row:raise ValueError('用户不存在')
            role=data.get('role',row['role']);disabled=int(bool(data.get('disabled',row['disabled'])))
            if role not in ('admin','user'):raise ValueError('无效权限组')
            if row['role']=='admin' and (role!='admin' or disabled):
                count=c.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0").fetchone()[0]
                if count<=1:raise ValueError('必须保留至少一个可用管理员')
            c.execute('UPDATE users SET role=?,disabled=? WHERE id=?',(role,disabled,target))
            c.execute('DELETE FROM sessions WHERE user_id=?',(target,))
        self.log(actor,'admin','USER_PERMISSION_CHANGED','已调整用户 '+row['username']+' 的权限或可用状态',category='admin')
    def rate_limit(self,bucket,limit=12,minutes=15):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT * FROM rate_limits WHERE bucket=?',(bucket,)).fetchone()
            if not row or row['reset_at']<now():
                c.execute('INSERT OR REPLACE INTO rate_limits VALUES(?,?,?)',(bucket,1,later(minutes)));return True
            if row['attempts']>=limit:return False
            c.execute('UPDATE rate_limits SET attempts=attempts+1 WHERE bucket=?',(bucket,));return True
