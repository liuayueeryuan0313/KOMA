"""课间 / KOMA — small multi-user calendar service. Copyright 2026 安稳."""
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from core import Store,ROOT,DISCLAIMER,DISCLAIMER_VERSION,password_hash
from sync import SyncManager
from school_profiles import prepare_school_config,prepare_clock_config,school_changed

class APIError(Exception):
    def __init__(self,status,message):self.status=status;self.message=message

class CalendarServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,store,manager,public_url=None):
        self.store=store;self.manager=manager
        self.public_url=(public_url or os.getenv('PUBLIC_URL') or f'http://localhost:{address[1]}').rstrip('/')
        parsed=urlsplit(self.public_url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.path not in ('','/') or parsed.query or parsed.fragment:raise ValueError('PUBLIC_URL must be an HTTP(S) origin without a path')
        self.secure=os.getenv('COOKIE_SECURE','false').lower()=='true' or self.public_url.startswith('https://')
        self.registration=os.getenv('ALLOW_REGISTRATION','true').lower()=='true'
        super().__init__(address,Handler)
        if address[1]==0 and not public_url:self.public_url=f'http://localhost:{self.server_port}'

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='KOMA/0.1'
    def log_message(self,*args):pass  # Never log private subscription paths, cookies or credential bodies.
    def response(self,status,data=b'',content_type='application/json; charset=utf-8',headers=None):
        if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False).encode()
        if isinstance(data,str):data=data.encode('utf-8')
        self.send_response(status)
        common={'Content-Type':content_type,'Content-Length':str(len(data)),'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"}
        common.update(headers or {})
        for key,value in common.items():self.send_header(key,value)
        self.end_headers()
        if self.command!='HEAD' and data:self.wfile.write(data)
    def body(self):
        if not self.headers.get('Content-Type','').lower().startswith('application/json'):raise APIError(415,'仅接受JSON请求')
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise APIError(400,'无效请求长度') from None
        if not 0<length<=256*1024:raise APIError(413,'请求内容过大或为空')
        try:
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):raise ValueError()
            return data
        except (ValueError,UnicodeError):raise APIError(400,'请求内容不是有效JSON') from None
    def token(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie','')[:8192])
        except Exception:return ''
        return cookie['koma_session'].value if 'koma_session' in cookie else ''
    def user(self,mutating=False,admin=False):
        user=self.server.store.authenticate(self.token())
        if not user:raise APIError(401,'请先登录')
        if mutating and not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),user['csrf']):raise APIError(403,'请求校验失败，请刷新页面')
        if admin and user['role']!='admin':raise APIError(403,'需要管理员权限')
        return user
    def check_origin(self):
        origin=self.headers.get('Origin')
        expected=urlsplit(self.server.public_url)
        allowed={f'{expected.scheme}://{expected.netloc}',f'http://localhost:{self.server.server_port}',f'http://127.0.0.1:{self.server.server_port}'}
        if origin and origin not in allowed:raise APIError(403,'来源校验失败')
    def session_response(self,user):
        token,csrf=self.server.store.session(user['id'])
        cookie='koma_session='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800'+('; Secure' if self.server.secure else '')
        self.response(200,{'user':user,'csrf':csrf},headers={'Set-Cookie':cookie})
    def do_GET(self):self.dispatch()
    def do_HEAD(self):self.dispatch()
    def do_POST(self):self.dispatch()
    def do_PUT(self):self.dispatch()
    def do_PATCH(self):self.dispatch()
    def do_DELETE(self):self.dispatch()
    def dispatch(self):
        try:self.route()
        except APIError as error:self.response(error.status,{'error':error.message})
        except (ValueError,TypeError,KeyError) as error:
            # Only local validation messages are emitted; school bodies never reach this layer.
            self.response(400,{'error':str(error)[:180] if isinstance(error,ValueError) else '输入格式无效'})
        except sqlite3.Error:self.response(503,{'error':'数据库暂时不可用，请稍后重试'})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.response(500,{'error':'服务暂时不可用；最近成功课表仍被保留'})
    def route(self):
        path=urlsplit(self.path).path;method=self.command;store=self.server.store
        if method in ('GET','HEAD'):
            if path=='/healthz':return self.response(200,{'status':'ok','version':'0.3.0'})
            if path=='/api/bootstrap':return self.response(200,{'setup_required':not store.has_admin(),'registration_open':self.server.registration,'disclaimer':DISCLAIMER,'disclaimer_version':DISCLAIMER_VERSION,'developer':'安稳'})
            static={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/mascot.svg':('mascot.svg','image/svg+xml'),'/favicon.ico':('mascot.svg','image/svg+xml')}
            if path in static:
                name,content_type=static[path];return self.response(200,(ROOT/'web'/name).read_bytes(),content_type)
            if path=='/api/session':
                user=self.user();return self.response(200,{'user':store.user(user['id']),'csrf':user['csrf']})
            if path=='/api/dashboard':
                user=self.user();return self.response(200,store.dashboard(user['id'],self.server.public_url))
            if path=='/api/admin/users':
                self.user(admin=True);return self.response(200,{'users':store.admin_users()})
            match=re.fullmatch(r'/cal/([A-Za-z0-9_-]{40,64})/(teaching|lab|combined)\.ics',path)
            if match:
                token,kind=match.groups();cal=store.calendar_for_token(token,kind)
                if not cal:raise APIError(404,'订阅链接不存在、已失效或课表尚未生成')
                etag='"'+cal['etag']+'"';unchanged=self.headers.get('If-None-Match')==etag
                if method=='GET':store.log(cal['user_id'],kind,'CALENDAR_NOT_MODIFIED' if unchanged else 'CALENDAR_DELIVERED','日历客户端检查订阅，内容未变化' if unchanged else '已向日历客户端提供最新成功版本',category='delivery')
                return self.response(304 if unchanged else 200,b'' if unchanged else cal['ics'],'text/calendar; charset=utf-8',{'ETag':etag,'Cache-Control':'private, max-age=300','Content-Disposition':'inline; filename="'+kind+'.ics"'})
        else:
            self.check_origin()
            data=self.body()
            if path in ('/api/login','/api/register','/api/setup') and method=='POST':
                if not store.rate_limit(path+':'+self.client_address[0]):raise APIError(429,'尝试过于频繁，请稍后重试')
                if path=='/api/login':return self.session_response(store.login(data.get('username',''),data.get('password','')))
                if not data.get('consent'):raise APIError(400,'请先阅读并同意使用说明与免责声明')
                if path=='/api/register':
                    if not self.server.registration:raise APIError(403,'管理员已关闭自行注册')
                    return self.session_response(store.create_user(data.get('username',''),data.get('password','')))
                token=data.get('setup_token')
                if not isinstance(token,str) or not token:raise APIError(403,'请填写一次性管理员设置码')
                return self.session_response(store.create_user(data.get('username',''),data.get('password',''),'admin',token))
            user=self.user(mutating=True)
            platform_match=re.fullmatch(r'/api/platforms/(app|jw|lab)/(test|login)',path)
            if platform_match and method=='POST':
                platform,action=platform_match.groups()
                if self.server.manager.busy(user['id']):raise APIError(409,'已有学校任务，请等待完成')
                if not store.rate_limit('platform:'+user['id'],limit=12,minutes=15):raise APIError(429,'平台操作过于频繁，请稍后重试')
                if action=='login':
                    if platform=='app' and not data.get('ack_app_relogin'):raise APIError(400,'请确认本次App登录可能使手机会话退出')
                    fields={key:data[key] for key in ('student_id','campus_password','jw_password','app_token','school_profile','school_custom','period_times') if key in data}
                    if fields:store.update_settings(user['id'],fields)
                credentials=None;test_config=None
                if action=='test':
                    saved=store.settings(user['id']);test_config=prepare_clock_config(prepare_school_config(saved['config'],data),data)
                    credentials={} if school_changed(saved['config'],test_config) else dict(saved['credentials'])
                    entered_id=str(data.get('student_id',credentials.get('student_id',''))).strip()
                    if entered_id!=credentials.get('student_id'):credentials={}
                    credentials['student_id']=entered_id
                    if entered_id and not re.fullmatch(r'[A-Za-z0-9]{5,32}',entered_id):raise APIError(400,'请填写正确学号')
                    for field in ('campus_password','jw_password','app_token'):
                        value=data.get(field)
                        if value:
                            if not isinstance(value,str) or len(value)>(4096 if field=='app_token' else 256):raise APIError(400,'凭据格式无效')
                            credentials['token' if field=='app_token' else field]=value
                    if platform=='app' and not credentials.get('token'):raise APIError(400,'请先获取或填写App token；App测试只用token拉取，不触发登录')
                self.server.manager.submit_platform(user['id'],platform,action,credentials,test_config)
                return self.response(202,{'state':'queued','platform':platform,'action':action})
            if path=='/api/logout' and method=='POST':
                store.logout(self.token());return self.response(200,{'ok':True},headers={'Set-Cookie':'koma_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'})
            if path=='/api/settings' and method=='PUT':
                if self.server.manager.busy(user['id']):raise APIError(409,'同步进行中，完成后再修改设置')
                return self.response(200,store.update_settings(user['id'],data))
            if path=='/api/sync' and method=='POST':
                scope=data.get('scope');kinds=['teaching','lab'] if scope=='all' else [scope]
                initialize=bool(data.get('initialize_app',False))
                if initialize:raise APIError(400,'App登录仅用于获取token，请使用App登录获取token按钮；课表同步直接使用token')
                self.server.manager.submit(user['id'],kinds,initialize);return self.response(202,{'state':'queued'})
            match=re.fullmatch(r'/api/links/(teaching|lab|combined)/rotate',path)
            if match and method=='POST':
                store.rotate(user['id'],match[1]);return self.response(200,{'links':store.links(user['id'],self.server.public_url)})
            match=re.fullmatch(r'/api/admin/users/([a-f0-9]{32})',path)
            if match and method=='PATCH':
                self.user(admin=True);store.admin_update(user['id'],match[1],data);return self.response(200,{'ok':True})
            if path=='/api/account/password' and method=='POST':
                store.login(user['username'],data.get('current_password',''));hashed=password_hash(data.get('new_password',''))
                with store.db() as c:
                    c.execute('UPDATE users SET password_hash=? WHERE id=?',(hashed,user['id']))
                    c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                return self.response(200,{'ok':True})
        raise APIError(404,'页面或接口不存在')

def main():
    store=Store(os.getenv('DATA_DIR',str(ROOT/'data')))
    if not store.has_admin() and os.getenv('ADMIN_USERNAME') and os.getenv('ADMIN_PASSWORD'):
        store.create_user(os.environ['ADMIN_USERNAME'],os.environ['ADMIN_PASSWORD'],'admin')
    manager=SyncManager(store);host=os.getenv('HOST','127.0.0.1');port=int(os.getenv('PORT','8080'))
    server=CalendarServer((host,port),store,manager);manager.start()
    print(f'课间 / KOMA · http://{host}:{server.server_port}',flush=True)
    if not store.has_admin():print('首次管理员设置码保存在 '+str(store.setup_path)+'，完成设置后自动失效。',flush=True)
    try:server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:pass
    finally:server.server_close();manager.close()

if __name__=='__main__':main()
