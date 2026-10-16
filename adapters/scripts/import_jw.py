"""Import captured JW HAR or sanitized Cookie-fetch response into the common snapshot."""
import argparse
import base64
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from compile_calendar import atomic_write

ORIGIN = 'https://jw.sdut.edu.cn'
PATH = '/jwglxt/kbcx/xskbcx_cxXsgrkb.html'
PERIOD_PATH = '/jwglxt/kbcx/xskbcx_cxRjc.html'
FIELDS = ['kch','kch_id','kcmc','xqj','xqjmc','jcs','zcd','cdmc','xqmc','xm','jxbmc','xnm','xqm']


def weeks(expression):
    expression=str(expression).replace('（','(').replace('）',')').replace('，',',').replace('、',',').replace('－','-').replace('–','-')
    values=set()
    for item in expression.split(','):
        part=re.fullmatch(r'(?:第)?(\d+)(?:-(\d+))?周(?:\(([单双])\))?',item.strip())
        if not part:
            raise ValueError('Unknown week expression: '+item)
        start,end,parity=part.groups(); start,end=int(start),int(end or start)
        if not 1<=start<=end<=53: raise ValueError('Invalid week range')
        values.update(w for w in range(start,end+1) if parity is None or w%2==(1 if parity=='单' else 0))
    if not values: raise ValueError('Empty week expression')
    return sorted(values)


def decode_entry(entry):
    if entry['response']['status']!=200: raise ValueError('Captured request not successful')
    content=entry['response']['content']
    text=content.get('text')
    if text is None: raise ValueError('HAR lacks response content; export with response bodies')
    if content.get('encoding')=='base64': text=base64.b64decode(text,validate=True).decode('utf-8')
    elif content.get('encoding'): raise ValueError('Unknown HAR encoding')
    return json.loads(text)


def form(entry):
    post=entry['request'].get('postData',{})
    return {p['name']:str(p.get('value','')) for p in post['params']} if post.get('params') else {k:v[-1] for k,v in parse_qs(post.get('text',''),keep_blank_values=True).items()}


def load_har(har,profile):
    matches=[]
    for entry in har.get('log',{}).get('entries',[]):
        request=entry['request']; url=urlsplit(request['url'])
        if request['method']!='POST' or f'{url.scheme}://{url.netloc}'!=ORIGIN or url.path!=PATH: continue
        if parse_qs(url.query).get('gnmkdm')!=['N2151']: continue
        parameters=form(entry)
        if parameters.get('xnm')==profile['form']['xnm'] and parameters.get('xqm')==profile['form']['xqm']: matches.append(entry)
    if not matches: raise ValueError('No matching successful timetable request in HAR')
    chosen=matches[-1]; data=decode_entry(chosen)
    if not isinstance(data,dict) or not isinstance(data.get('kbList'),list): raise ValueError('Expected kbList; possible expired login')
    sanitized={
        'schemaVersion':1,'adapter':'jw-web','fetchedAt':chosen.get('startedDateTime'),
        'request':{'xnm':profile['form']['xnm'],'xqm':profile['form']['xqm'],'gnmkdm':'N2151'},
        'calendarTerm':profile['calendarTerm'],'maxWeekNumber':profile['maxWeekNumber'],
        'kbList':[{k:r[k] for k in FIELDS if k in r} for r in data['kbList']],
        'sjkList':[{k:r[k] for k in ['kcmc','qsjsz','jsxm','xqmc'] if k in r} for r in data.get('sjkList',[])],
        'periods':[]}
    for entry in har.get('log',{}).get('entries',[]):
        url=urlsplit(entry['request']['url']); p=form(entry)
        if entry['request']['method']=='POST' and f'{url.scheme}://{url.netloc}'==ORIGIN and url.path==PERIOD_PATH and p.get('xnm')==profile['form']['xnm'] and p.get('xqm')==profile['form']['xqm'] and p.get('xqh_id')==profile['periodsForm']['xqh_id']:
            periods=decode_entry(entry)
            if not isinstance(periods,list): raise ValueError('Invalid periods response')
            sanitized['periods']=[{k:r.get(k) for k in ['jcmc','qssj','jssj']} for r in periods]
    evidence={'source':'user-provided browser HAR','capturedAt':chosen.get('startedDateTime'),
              'method':'POST','url':ORIGIN+PATH+'?gnmkdm=N2151','form':form(chosen),
              'httpStatus':chosen['response']['status'],'scheduledRules':len(sanitized['kbList']),
              'unscheduledCourses':len(sanitized['sjkList']),'periods':sanitized['periods'],
              'cookiePresentInHAR':any(h['name'].lower()=='cookie' for h in chosen['request'].get('headers',[])) or bool(chosen['request'].get('cookies')),
              'responseSHA256':hashlib.sha256(chosen['response']['content'].get('text','').encode()).hexdigest(),
              'cookieReplayTested':False}
    return sanitized,evidence


def convert(payload,config,profile):
    if payload.get('adapter')!='jw-web' or not isinstance(payload.get('kbList'),list): raise ValueError('Invalid JW envelope')
    if payload['calendarTerm']!=config['term'] or profile['calendarTerm']!=config['term']: raise ValueError('Term mismatch')
    if payload['request']['xnm']!=profile['form']['xnm'] or payload['request']['xqm']!=profile['form']['xqm']: raise ValueError('Request term mismatch')
    maximum=int(payload['maxWeekNumber'])
    if maximum!=profile['maxWeekNumber'] or not 1<=maximum<=53: raise ValueError('Invalid maximum week')
    first=date.fromisoformat(config['week1_monday'])
    if first.weekday()!=0: raise ValueError('First week must begin Monday')
    rows=[]
    for rule in payload['kbList']:
        if str(rule.get('xnm'))!=profile['form']['xnm'] or str(rule.get('xqm'))!=profile['form']['xqm']: raise ValueError('Mixed terms in kbList')
        periods=re.fullmatch(r'(\d+)(?:-(\d+))?',str(rule['jcs']).strip())
        if not periods: raise ValueError('Unknown period expression')
        start,end=int(periods[1]),int(periods[2] or periods[1])
        day=int(rule['xqj'])
        if not 1<=start<=end or not 1<=day<=7: raise ValueError('Invalid day or periods')
        # kch is the common course code; kch_id may be an unrelated internal UUID.
        course_id=str(rule.get('kch') or rule.get('kch_id') or 'name:'+rule['kcmc'])
        for week in weeks(rule['zcd']):
            if week>maximum: raise ValueError('Week exceeds configured term')
            rows.append({'xnxq':config['term'],'kcdm':course_id,'kcmc':rule['kcmc'],'skzc':str(week),
                         'xq':'星期'+'一二三四五六日'[day-1],'ksjc':str(start),'jsjc':str(end),
                         'jxdd':rule.get('cdmc',''),'campus':rule.get('xqmc',''),
                         'teacher':rule.get('xm',''),'className':rule.get('jxbmc','')})
    rows.sort(key=lambda r:(int(r['skzc']),'一二三四五六日'.index(r['xq'][-1]),int(r['ksjc']),r['kcdm']))
    period_map={}
    for p in payload.get('periods',[]):
        key=str(p['jcmc']); values=[p['qssj'],p['jssj']]
        if key in config['periods'] and config['periods'][key]!=values: raise ValueError('Captured class times conflict with config for period '+key)
        period_map[key]=values
    base=config.get('school_custom',{}).get('jw_base','')+'/kbcx/xskbcx_cxXsgrkb.html' if config.get('school_profile')=='custom' else ORIGIN+PATH
    return {'fetchedAt':payload.get('fetchedAt'),'source':base,'sourceAdapter':'jw-web',
            'xnxq':config['term'],'weekNumber':None,'maxWeekNumber':maximum,'beginDate':first.isoformat(),
            'endDate':(first+timedelta(weeks=maximum,days=-1)).isoformat(),'rows':rows,
            'unscheduled':[{'name':r.get('kcmc',''),'weeks':r.get('qsjsz',''),'teacher':r.get('jsxm',''),'campus':r.get('xqmc','')} for r in payload.get('sjkList',[])],
            'capturedPeriods':period_map,'metadataBasis':'term start and total weeks from explicit config/profile; website HAR does not supply these values'}


def main():
    parser=argparse.ArgumentParser(description=__doc__); group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--har');group.add_argument('--response')
    parser.add_argument('--config',default='config.json');parser.add_argument('--request-config',default='jw-request.json')
    parser.add_argument('--output',default='build/timetable-jw.json');parser.add_argument('--allow-empty',action='store_true')
    parser.add_argument('--sanitized-response-output');parser.add_argument('--evidence-output');args=parser.parse_args()
    try:
        read=lambda path:json.loads(Path(path).read_text(encoding='utf-8-sig'))
        config,profile=read(args.config),read(args.request_config)
        if args.har: payload,evidence=load_har(read(args.har),profile)
        else: payload,evidence=read(args.response),{'source':'sanitized website HTTP response','cookieReplayTested':False}
        result=convert(payload,config,profile)
        if not result['rows'] and not args.allow_empty: raise ValueError('Empty timetable; existing file retained')
        for path,data in [(args.sanitized_response_output,payload),(args.evidence_output,evidence),(args.output,result)]:
            if path: atomic_write(path,json.dumps(data,ensure_ascii=False,indent=2))
        print(json.dumps({'state':'READY','adapter':'jw-web','scheduledRules':len(payload['kbList']),'occurrences':len(result['rows']),'unscheduled':len(result['unscheduled']),'output':args.output},ensure_ascii=False))
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'state':'DATA_INVALID','message':str(error)},ensure_ascii=False));raise SystemExit(4)


if __name__=='__main__':main()
