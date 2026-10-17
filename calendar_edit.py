"""Create manual lessons or store field overrides over school occurrences."""
import json
import secrets
from datetime import date, timedelta
from core import json_text, now
from adapters.scripts.compile_calendar import normalize
from calendar_layers import (TIME_FIELDS, TEXT_FIELDS, ensure_layers, effective_rows,
                             rebuild, assert_editable)


def save_occurrence(store, user_id, kind, values, identifier=None):
    if kind not in ('teaching','lab'): raise ValueError('请选择教学或实验课表')
    config = store.settings(user_id)['config']
    def text(field, required=False):
        value = values.get(field,'')
        if not isinstance(value,str) or len(value)>200: raise ValueError('课程文字字段格式或长度无效')
        value = value.strip()
        if required and not value: raise ValueError('请填写课程名称')
        return value
    def integer(field):
        value = values.get(field)
        if isinstance(value,bool) or not str(value).isdigit(): raise ValueError('周次、星期和节次须为整数')
        return int(value)
    entered = {field:integer(field) for field in TIME_FIELDS}
    entered.update(name=text('name',True),location=text('location'),teacher=text('teacher'))
    if kind=='lab': entered.update(courseName=text('courseName') or entered['name'],projectName=text('projectName') or entered['name'])
    if not 1<=entered['week']<=config['maxWeekNumber'] or not 1<=entered['weekday']<=7 or not 1<=entered['startPeriod']<=entered['endPeriod']<=99:
        raise ValueError('周次、星期或节次超出范围')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE'); assert_editable(c,user_id)
        ensure_layers(c,user_id,kind,config)
        current = next((r for r in effective_rows(c,user_id,kind,config) if r['occurrenceId']==identifier),None) if identifier else None
        if identifier and not current: raise ValueError('课程已不存在，请刷新课表')
        if current and values.get('revision') and values['revision']!=current['revision']: raise ValueError('课程已变更，请刷新后重新编辑')
        identifier = identifier or secrets.token_hex(32)
        # Validate new clock values using the same school timetable normalizer.
        first=date.fromisoformat(config['week1_monday'])
        raw=dict(xnxq=config['term'],kcdm=current['courseId'] if current else kind+':manual:'+identifier,kcmc=entered['name'],skzc=str(entered['week']),xq='星期'+'一二三四五六日'[entered['weekday']-1],ksjc=str(entered['startPeriod']),jsjc=str(entered['endPeriod']),jxdd=entered['location'],teacher=entered['teacher'])
        if kind=='lab': raw.update(activityType='laboratory',courseName=entered['courseName'],projectName=entered['projectName'],selectionType=(current or {}).get('selectionType','手动安排'))
        normalized=normalize(dict(xnxq=config['term'],beginDate=first.isoformat(),maxWeekNumber=config['maxWeekNumber'],rows=[raw]),config)['occurrences']
        if not normalized: raise ValueError('该日期已在学期配置中取消，请选择其他日期')
        if not current or current['origin']=='manual':
            baseline, fields, mode=normalized[0],{},'create'
        else:
            mode='override'
            previous=c.execute('SELECT baseline,fields FROM manual_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=?',(user_id,kind,config['term'],identifier)).fetchone()
            school=c.execute('SELECT row FROM school_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=?',(user_id,kind,config['term'],identifier)).fetchone()
            latest=json.loads(school['row'])
            latest['teacher']=current['schoolArrangement'].get('teacher','') if current.get('schoolArrangement') else latest.get('teacher','')
            if not previous: latest['teacher']=current.get('teacher','')
            baseline=json.loads(previous['baseline']) if previous else dict(latest)
            fields=json.loads(previous['fields']) if previous else {}
            for field in TEXT_FIELDS:
                if field in entered and entered[field]!=current.get(field,''):
                    if entered[field]==latest.get(field,''): fields.pop(field,None)
                    else: fields[field]=entered[field];baseline[field]=latest.get(field,'')
            if any(entered[field]!=current[field] for field in TIME_FIELDS):
                for field in TIME_FIELDS:
                    baseline[field]=latest[field]
                    if all(entered[f]==latest[f] for f in TIME_FIELDS): fields.pop(field,None)
                    else: fields[field]=entered[field]
        if mode=='override' and not fields:
            c.execute('DELETE FROM manual_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=?',(user_id,kind,config['term'],identifier))
        else:
            c.execute('INSERT OR REPLACE INTO manual_occurrences VALUES(?,?,?,?,?,?,?)',(user_id,kind,config['term'],identifier,mode,json_text(baseline),json_text(fields)))
        rebuild(c,user_id,config)
        c.execute('INSERT INTO logs(user_id,kind,category,level,event,message,created_at) VALUES(?,?,?,?,?,?,?)',(user_id,kind,'sync','info','OCCURRENCE_EDITED' if current else 'OCCURRENCE_CREATED','已保存课程手动修改' if current else '已手动新建课程',now()))
        result=next(r for r in effective_rows(c,user_id,kind,config) if r['occurrenceId']==identifier)
    return {**result,'kind':kind}


def delete_occurrence(store, user_id, kind, identifier, expected_revision=None):
    """Delete one occurrence, retaining a tombstone for school-provided rows."""
    if kind not in ('teaching', 'lab'): raise ValueError('请选择教学或实验课表')
    config = store.settings(user_id)['config']
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE'); assert_editable(c, user_id)
        ensure_layers(c, user_id, kind, config)
        row = next((r for r in effective_rows(c, user_id, kind, config) if r['occurrenceId'] == identifier), None)
        if not row: raise ValueError('课程已不存在，请刷新课表')
        if expected_revision and expected_revision != row['revision']:
            raise ValueError('课程已变更，请刷新后重新操作')
        if row['origin'] == 'manual':
            c.execute("DELETE FROM manual_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=? AND mode='create'",
                      (user_id, kind, config['term'], identifier))
        else:
            c.execute('INSERT OR REPLACE INTO deleted_occurrences VALUES(?,?,?,?,?)',
                      (user_id, kind, config['term'], identifier, now()))
            c.execute('DELETE FROM manual_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=?',
                      (user_id, kind, config['term'], identifier))
        rebuild(c, user_id, config)
        c.execute('INSERT INTO logs(user_id,kind,category,level,event,message,created_at) VALUES(?,?,?,?,?,?,?)',
                  (user_id, kind, 'sync', 'info', 'OCCURRENCE_DELETED', '已删除课程', now()))
