"""Scheduled/manual synchronization; failover belongs to teaching calendars only."""
import json
import os
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from core import ROOT, now, later, json_text

sys.path.insert(0,str(ROOT/'adapters/scripts'))
from compile_calendar import normalize,compile_calendar
from import_jw import convert as convert_jw
from import_lab import convert as convert_lab
from merge_snapshots import merge

MESSAGES={
 'TOKEN_REQUIRED':'App token 已失效或尚未取得',
 'SCHOOL_ENDPOINT_MISSING':'当前学校尚未配置此平台的服务地址或应用参数，请在学校与平台设置中补充',
 'SCHOOL_CONFIG_INVALID':'自定义学校地址或接口参数格式无效',
 'SCHOOL_ADDRESS_NOT_PUBLIC':'学校域名解析到本机、内网或保留地址，已停止请求',
 'UNEXPECTED_AUTH_ORIGIN':'学校认证跳转到未配置的域名，已停止发送凭据',
 'CREDENTIALS_MISSING':'学校账户或对应密码尚未配置',
 'HUMAN_CAPTCHA_REQUIRED':'学校要求人工验证码，请完成学校认证后再同步',
 'HUMAN_VERIFICATION_REQUIRED':'教务系统要求人工验证码',
 'SMS_VERIFICATION_REQUIRED':'教务系统要求短信验证',
 'LOGIN_FAILED':'学校拒绝登录，请检查对应系统的密码',
 'AUTHENTICATION_FAILED':'学校认证未成功，请核对密码或认证要求',
 'FETCH_FAILED':'学校接口查询失败，请稍后重试',
 'EMPTY_TIMETABLE':'学校返回整学期空课表，已保留旧版',
 'EMPTY_OR_INCOMPLETE_LAB_TIMETABLE':'实验课表为空或分页不完整，已保留旧版',
 'INVALID_TERM_PROFILE':'教务学期参数未配置完整',
 'STUDENT_ID_MISMATCH':'学校响应的学号与当前账户不一致',
 'AUTHENTICATION_OR_NETWORK_FAILED':'学校认证或网络请求失败',
 'NETWORK_OR_PROTOCOL_ERROR':'学校网络或协议请求未完成，请稍后重试',
 'LAB_FETCH_FAILED':'已完成实验平台登录，但课表接口查询失败',
 'LAB_CAS_EXCHANGE_FAILED':'实验平台统一门户身份交换未完成，请稍后重试',
 'INVALID_PAGINATION':'学校实验课表分页不完整，拉取校验未通过',
 'PAGINATION_CHANGED_DURING_FETCH':'实验课表在拉取期间发生变化，请重新测试',
 'ACCOUNT_FAILURE_LIMIT_REQUIRES_HUMAN_REVIEW':'教务系统登录失败次数达到限制，请先在学校页面处理',
}

class SourceError(Exception):
    def __init__(self,code,message=None):self.code=code;super().__init__(message or MESSAGES.get(code,'学校认证或接口格式发生变化，已保留最近成功课表'))

class Bridge:
    def __init__(self,node=None):self.node=node or os.getenv('NODE_BIN') or shutil.which('node')
    def call(self,operation,credentials,config):
        if not self.node:raise SourceError('NODE_RUNTIME_UNAVAILABLE')
        try:
            result=subprocess.run([self.node,str(ROOT/'adapters/school_bridge.mjs')],input=json_text({'operation':operation,'credentials':credentials,'config':config}),capture_output=True,text=True,encoding='utf-8',timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            payload=json.loads(result.stdout)
            if result.returncode or not payload.get('ok'):raise SourceError(payload.get('code','FETCH_FAILED'))
            return payload
        except (OSError,ValueError,subprocess.TimeoutExpired):raise SourceError('FETCH_FAILED') from None

class SyncManager:
    def __init__(self,store,bridge=None):
        self.store=store;self.bridge=bridge or Bridge();self.pool=ThreadPoolExecutor(max_workers=3,thread_name_prefix='school-sync')
        self.lock=threading.Lock();self.pending=set();self.stopped=threading.Event()
        self.scheduler=threading.Thread(target=self._schedule,daemon=True,name='calendar-scheduler')
    def start(self):self.scheduler.start()
    def busy(self,user_id):
        with self.lock:return user_id in self.pending
    def submit(self,user_id,kinds,initialize_app=False):
        if not kinds or any(k not in ('teaching','lab') for k in kinds):raise ValueError('请选择教学课表或实验课表')
        with self.lock:
            if user_id in self.pending:raise ValueError('已有同步任务，请等待完成')
            self.pending.add(user_id)
        try:
            with self.store.db() as c:
                for kind in kinds:c.execute("UPDATE sync_state SET state='queued',last_attempt=? WHERE user_id=? AND kind=?",(now(),user_id,kind))
            return self.pool.submit(self._job,user_id,tuple(dict.fromkeys(kinds)),initialize_app)
        except Exception:
            with self.lock:self.pending.discard(user_id)
            raise
    def _schedule(self):
        while not self.stopped.wait(15):
            self.schedule_due()
    def submit_platform(self,user_id,platform,action,credentials=None,config=None):
        if platform not in ('app','jw','lab') or action not in ('test','login'):raise ValueError('无效平台操作')
        with self.lock:
            if user_id in self.pending:raise ValueError('已有学校任务，请等待完成')
            self.pending.add(user_id)
        try:
            self.store.platform_check(user_id,platform,action,'running','正在验证登录并拉取完整课表' if action=='test' else '正在验证学校登录')
            return self.pool.submit(self._platform_job,user_id,platform,action,credentials,config)
        except Exception:
            with self.lock:self.pending.discard(user_id)
            raise
    def _platform_job(self,user_id,platform,action,credentials,config=None):
        try:
            user=self.store.user(user_id)
            if not user or user['disabled']:return
            settings=self.store.settings(user_id);kind='lab' if platform=='lab' else 'teaching'
            if config is not None:settings['config']=config
            creds=dict(credentials if credentials is not None else settings['credentials'])
            operation={'app':'app_fetch','jw':'jw_fetch','lab':'lab_fetch'}[platform] if action=='test' else {'app':'app_init','jw':'jw_login','lab':'lab_login'}[platform]
            try:
                if action=='test' and platform=='app' and not creds.get('token'):
                    raise SourceError('TOKEN_REQUIRED','尚无 App token，请先获取或填写 token；App 测试只用 token 拉取，不会触发登录')
                response=self._school_call(user_id,kind,operation,creds,settings['config'])
                identity={}
                if action=='test':
                    identity=response.get('identity') or response.get('payload',{}).get('identity',{})
                    if platform=='app':snapshot=response['snapshot']
                    elif platform=='lab':snapshot=convert_lab(response['payload'],settings['config'])
                    else:
                        profile=json.loads((ROOT/'adapters/jw-request.json').read_text(encoding='utf-8'))
                        profile.update(calendarTerm=settings['config']['term'],maxWeekNumber=settings['config']['maxWeekNumber'])
                        profile['form'].update(xnm=settings['config']['term'].split('-')[0],xqm=settings['config']['jw_semester_code'])
                        profile['periodsForm'].update(xnm=profile['form']['xnm'],xqm=profile['form']['xqm'])
                        snapshot=convert_jw(response['payload'],settings['config'],profile)
                    normalized=normalize(snapshot,settings['config'])
                    if not normalized['occurrences']:raise SourceError('EMPTY_TIMETABLE')
                    _,metrics=compile_calendar(normalized,settings['config'])
                    if str(identity.get('studentId',''))!=creds.get('student_id'):raise SourceError('STUDENT_ID_MISMATCH')
                    message=('token 课表拉取验证通过' if platform=='app' else '登录与课表拉取验证通过')+f"，共{metrics['occurrences']}课次；测试未保存凭据、未更新订阅"
                else:
                    identity=response.get('identity') or response.get('payload',{}).get('identity',{})
                    if str(identity.get('studentId',''))!=creds.get('student_id'):raise SourceError('STUDENT_ID_MISMATCH')
                    if platform=='app':self.store.save_secret(user_id,{'token':response['token'],'app_identity':identity})
                    name=str(identity.get('name','')).strip()
                    if name and name!=identity['studentId']:
                        with self.store.db() as c:c.execute('UPDATE users SET student_name=? WHERE id=?',(name[:100],user_id))
                    message='登录验证成功'+('，App token 已加密保存' if platform=='app' else '')+'；需要更新课表时请点击同步'
                self.store.platform_check(user_id,platform,action,'ok',message,identity)
            except SourceError as error:self.store.platform_check(user_id,platform,action,'error',str(error))
            except Exception:self.store.platform_check(user_id,platform,action,'error','平台检查未完成，请稍后重试；已有课表保持不变')
        finally:
            with self.lock:self.pending.discard(user_id)
    def schedule_due(self):
        with self.store.db() as c:rows=c.execute('SELECT sync_state.user_id,kind FROM sync_state JOIN users ON users.id=user_id WHERE enabled=1 AND next_run<=? AND users.disabled=0',(now(),)).fetchall()
        grouped={}
        for row in rows:grouped.setdefault(row['user_id'],[]).append(row['kind'])
        for user_id,kinds in grouped.items():
            try:self.submit(user_id,kinds)
            except ValueError:pass
    def _finish(self,user_id,kind,success=False,source=None,warning='',identity=None):
        with self.store.db() as c:
            plan=c.execute('SELECT enabled,interval_minutes FROM sync_state WHERE user_id=? AND kind=?',(user_id,kind)).fetchone()
            next_run=later(plan['interval_minutes']) if plan['enabled'] else None
            state=('warning' if warning else 'ok') if success else 'error'
            if success:
                name=str((identity or {}).get('name') or '').strip()[:100];student_id=str((identity or {}).get('studentId') or '')[:40]
                c.execute('UPDATE sync_state SET state=?,next_run=?,last_success=?,active_source=?,warning=?,identity_name=?,identity_id=? WHERE user_id=? AND kind=?',(state,next_run,now(),source,warning,name,student_id,user_id,kind))
                if name and name!=student_id:c.execute('UPDATE users SET student_name=? WHERE id=?',(name,user_id))
            else:c.execute('UPDATE sync_state SET state=?,next_run=?,warning=? WHERE user_id=? AND kind=?',(state,next_run,warning,user_id,kind))
    def _school_call(self,user_id,kind,operation,credentials,config):
        names={'app_init':'校园App登录授权','app_fetch':'校园App全学期课表拉取','jw_fetch':'教务系统登录及教学课表拉取','lab_fetch':'学生服务大厅统一门户登录及实验课表拉取','jw_login':'教务系统登录验证','lab_login':'实验平台统一门户登录验证','connect_app':'校园App连通性检查','connect_jw':'教务系统连通性检查','connect_lab':'实验平台及统一门户连通性检查'}
        name=names[operation]
        self.store.log(user_id,kind,'SCHOOL_REQUEST_STARTED',name+'：开始','info','school')
        try:response=self.bridge.call(operation,credentials,config)
        except SourceError as error:
            self.store.log(user_id,kind,'SCHOOL_REQUEST_FAILED',name+'：'+str(error),'error','school');raise
        if operation=='app_fetch':detail=f"，返回{len(response['snapshot']['rows'])}课次"
        elif operation=='jw_fetch':detail=f"，返回{len(response['payload']['kbList'])}条排课规则"
        elif operation=='lab_fetch':detail=f"，返回{len(response['payload']['pages'])}页、{sum(len(p['result']['list']) for p in response['payload']['pages'])}条实验安排"
        elif operation=='app_init':detail='，已取得新token'
        else:detail='，连接正常' if operation.startswith('connect_') else '，身份验证通过'
        self.store.log(user_id,kind,'SCHOOL_REQUEST_SUCCEEDED',name+'：成功'+detail,'info','school')
        return response
    def _fetch_jw(self,user_id,settings):
        response=self._school_call(user_id,'teaching','jw_fetch',settings['credentials'],settings['config'])
        profile=json.loads((ROOT/'adapters/jw-request.json').read_text(encoding='utf-8'))
        profile['calendarTerm']=settings['config']['term'];profile['maxWeekNumber']=settings['config']['maxWeekNumber']
        profile['form']['xnm']=str(settings['config']['term']).split('-')[0]
        profile['form']['xqm']=str(settings['config']['jw_semester_code'])
        profile['periodsForm'].update(xnm=profile['form']['xnm'],xqm=profile['form']['xqm'])
        return convert_jw(response['payload'],settings['config'],profile),response['payload'].get('identity',{})
    def _teaching(self,user_id,initialize_app):
        settings=self.store.settings(user_id);creds=settings['credentials'];mode=settings['mode'];warning=''
        if not creds.get('student_id'):raise SourceError('CREDENTIALS_MISSING')
        if initialize_app:
            if mode=='jw':raise ValueError('当前为教务系统独立模式，无需重新登录App')
            response=self._school_call(user_id,'teaching','app_init',creds,settings['config'])
            self.store.save_secret(user_id,{'token':response['token'],'app_identity':response.get('identity',{})})
            self.store.log(user_id,'teaching','APP_AUTHORIZED','本次已重新登录App并更新本地加密token')
            settings=self.store.settings(user_id);creds=settings['credentials']
        if mode=='jw':
            snapshot,identity=self._fetch_jw(user_id,settings);source='jw'
        else:
            try:
                if creds.get('token_invalid'):raise SourceError('TOKEN_REQUIRED')
                response=self._school_call(user_id,'teaching','app_fetch',creds,settings['config']);snapshot=response['snapshot'];identity=response.get('identity',{});source='app'
            except SourceError as error:
                if error.code=='TOKEN_REQUIRED':self.store.save_secret(user_id,{'token_invalid':True})
                if mode!='auto' or error.code!='TOKEN_REQUIRED':raise
                warning='App token 已失效，教学课表已切换至教务系统；自动更新不会登录App，需手动获取新token后恢复；实验课表独立'
                self.store.log(user_id,'teaching','FAILOVER_STARTED','App token 无效，开始使用教务系统获取教学课表','warning')
                try:snapshot,identity=self._fetch_jw(user_id,settings);source='jw'
                except SourceError as fallback:
                    self.store.log(user_id,'teaching','FAILOVER_FAILED','教学课表故障转移未成功，最近成功版本继续提供','error')
                    raise SourceError('FAILOVER_FAILED','App token 已失效，转至教务系统后仍未同步成功：'+str(fallback)+'；最近成功课表继续提供') from None
        if source=='jw':self.store.save_teacher_cache(user_id,snapshot['rows'])
        elif mode=='auto' and not settings['config'].get('course_details') and creds.get('jw_password'):
            # One-time metadata enrichment. App remains the authoritative timetable source.
            try:
                details,jw_identity=self._fetch_jw(user_id,settings)
                def course_keys(data):return {(r['kcdm'],r['skzc'],r['xq'],r['ksjc'],r['jsjc'],r['jxdd']) for r in data['rows']}
                if course_keys(details)==course_keys(snapshot):
                    self.store.save_teacher_cache(user_id,details['rows'])
                    if jw_identity.get('name'):identity=jw_identity
                    self.store.log(user_id,'teaching','TEACHER_METADATA_IMPORTED','已用本人教务记录补全教师信息；教学排课仍来自App')
            except (SourceError,ValueError,KeyError):
                self.store.log(user_id,'teaching','TEACHER_METADATA_UNAVAILABLE','教师信息未能补全；未推测缺失字段','warning')
        return snapshot,identity,source,warning
    def _lab(self,user_id):
        settings=self.store.settings(user_id)
        response=self._school_call(user_id,'lab','lab_fetch',settings['credentials'],settings['config'])
        snapshot=convert_lab(response['payload'],settings['config'])
        return snapshot,response['payload'].get('identity',{}),'lab-cas',''
    def _rebuild_combined(self,user_id,config):
        from calendar_layers import rebuild
        with self.store.db() as c:
            c.execute('BEGIN IMMEDIATE');rebuild(c,user_id,config)
    def _job(self,user_id,kinds,initialize_app):
        try:
            for kind in kinds:
                user=self.store.user(user_id)
                if not user or user['disabled']:break
                with self.store.db() as c:c.execute("UPDATE sync_state SET state='running',last_attempt=? WHERE user_id=? AND kind=?",(now(),user_id,kind))
                self.store.log(user_id,kind,'SYNC_STARTED','开始同步'+('教学课表' if kind=='teaching' else '实验课表'))
                try:
                    snapshot,identity,source,warning=self._teaching(user_id,initialize_app) if kind=='teaching' else self._lab(user_id)
                    config=self.store.settings(user_id)['config'];normalized=normalize(snapshot,config)
                    if not normalized['occurrences']:raise SourceError('EMPTY_TIMETABLE')
                    ics,metrics=compile_calendar(normalized,config);metrics['term']=snapshot['xnxq']
                    self.store.put_calendar(user_id,kind,snapshot,normalized,ics,metrics)
                    self._finish(user_id,kind,True,source,warning,identity)
                    self.store.log(user_id,kind,'SYNC_SUCCESS',f"同步完成，共{metrics['occurrences']}课次"+('；当前使用教务故障转移' if warning else ''),'warning' if warning else 'info')
                    published=self.store.calendar(user_id,'combined')
                    if published and json.loads(published['metrics']).get('conflicts'):
                        self.store.log(user_id,kind,'MANUAL_CONFLICT','学校安排有变更，已保留手动修改，请在课表中核对','warning')
                except SourceError as error:
                    self._finish(user_id,kind,warning=str(error));self.store.log(user_id,kind,error.code,str(error),'error')
                except (ValueError,KeyError,TypeError):
                    message='课表字段、日期或节次校验未通过，已保留最近成功版本'
                    self._finish(user_id,kind,warning=message);self.store.log(user_id,kind,'DATA_INVALID',message,'error')
                except Exception:
                    message='同步任务未完成，已保留最近成功版本；请查看服务运行状态'
                    self._finish(user_id,kind,warning=message);self.store.log(user_id,kind,'INTERNAL_ERROR',message,'error')
        finally:
            with self.lock:self.pending.discard(user_id)
    def close(self):self.stopped.set();self.pool.shutdown(wait=True,cancel_futures=True)
