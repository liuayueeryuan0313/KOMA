"""Offline import of complete SDUT laboratory timetable HAR pages. No HTTP replay."""
import argparse
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from compile_calendar import atomic_write, normalize
from import_jw import decode_entry

ORIGIN = 'https://syjxgl.sdut.edu.cn'
PATH = '/teach/teach/stuTime/listStuTimePage'
FIELDS = ['course_name','exp_name','week','week_day','jc_start','jc_end',
          'room_name','teacher_name','form','row_id']
SIGNATURE_HEADERS = ['nonce','random','signature','timestamp','zhxhsign']


def integer(value, name, minimum=1):
    if isinstance(value, bool) or not str(value).isdigit() or int(value)<minimum:
        raise ValueError('Invalid '+name)
    return int(value)


def load_har(har, config):
    pages, header_names, captures, captured_at = [], set(), 0, None
    for entry in har.get('log',{}).get('entries',[]):
        request=entry['request']; url=urlsplit(request['url'])
        if request['method']!='POST' or f'{url.scheme}://{url.netloc}'!=ORIGIN or url.path!=PATH:
            continue
        body=json.loads(request.get('postData',{}).get('text','{}'))
        if body.get('yearterm')!=config['term']:
            continue
        number=integer(body['currpage'],'request page')
        size=integer(body['pagesize'],'request page size')
        data=decode_entry(entry)
        if not isinstance(data,dict) or data.get('code')!=200 or not isinstance(data.get('result'),dict):
            raise ValueError('Laboratory response failed; existing calendar retained')
        result=data['result']
        if not isinstance(result.get('list'),list):
            raise ValueError('Laboratory response lacks rows')
        pages.append({'request':{'yearterm':body['yearterm'],'currpage':number,'pagesize':size},
                      'result':{**{k:result[k] for k in ['totalCount','pageSize','totalPage','currPage']},
                                'list':[{k:r[k] for k in FIELDS if k in r} for r in result['list']]}})
        header_names.update(h['name'].lower() for h in request.get('headers',[]))
        captured_at=entry.get('startedDateTime')
        captures+=1
    if not pages:
        raise ValueError('No matching laboratory timetable requests')
    # Preserve capture order: repeated page captures are replaced by the last one.
    payload={'schemaVersion':1,'adapter':'lab-har','calendarTerm':config['term'],'capturedAt':captured_at,'pages':pages}
    evidence={'method':'POST','url':ORIGIN+PATH,'capturedRequests':captures,
              'requestFields':['yearterm','currpage','pagesize'],
              'signatureHeaderNames':sorted(set(SIGNATURE_HEADERS)&header_names),
              'signatureValuesSaved':False,'liveReplayVerified':False,
              'rowIdMeaning':'Display row number; not a verified immutable experiment ID',
              'clockBasis':'User config: periods 1-10 and corrected combined period 11-12 range; not present in this HAR',
              'termBoundaryBasis':'Explicit config; not supplied by laboratory response'}
    return payload,evidence


def convert(payload, config):
    if payload.get('adapter')!='lab-har' or payload.get('calendarTerm')!=config['term']:
        raise ValueError('Invalid laboratory envelope or term')
    pages={}; counts=set(); sizes=set(); totals=set()
    for captured in payload['pages']:
        body,result=captured['request'],captured['result']
        if body['yearterm']!=config['term']:
            raise ValueError('Mixed laboratory terms')
        n=integer(body['currpage'],'request page'); size=integer(body['pagesize'],'request size')
        if integer(result['currPage'],'response page')!=n or integer(result['pageSize'],'response size')!=size:
            raise ValueError('Request and response pagination differ')
        total=integer(result['totalCount'],'total count',0); total_pages=integer(result['totalPage'],'total pages')
        if total_pages!=max(1,(total+size-1)//size) or n>total_pages:
            raise ValueError('Inconsistent laboratory pagination')
        counts.add(total); sizes.add(size); totals.add(total_pages)
        rows=result['list']
        if not isinstance(rows,list) or len(rows)!=min(size,max(0,total-(n-1)*size)):
            raise ValueError('Laboratory page row count differs from total')
        pages[n]=rows
    if not pages or len(counts)!=1 or len(sizes)!=1 or len(totals)!=1:
        raise ValueError('Missing or inconsistent laboratory pages')
    if set(pages)!=set(range(1,next(iter(totals))+1)):
        raise ValueError('Incomplete laboratory pages; existing calendar retained')
    rows=[]; seen=set()
    for n in sorted(pages):
        for record in pages[n]:
            if not isinstance(record['course_name'],str) or not isinstance(record['exp_name'],str):
                raise ValueError('Invalid laboratory course or project')
            course=record['course_name'].strip(); project=record['exp_name'].strip()
            if not course or not project:
                raise ValueError('Empty laboratory course or project')
            kind=integer(record['form'],'selection type')
            if kind not in (1,2): raise ValueError('Unknown laboratory selection type')
            week=integer(record['week'],'week'); day=integer(record['week_day'],'weekday')
            start=integer(record['jc_start'],'start period'); end=integer(record['jc_end'],'end period')
            if day>7 or week>config['maxWeekNumber'] or start>end:
                raise ValueError('Invalid laboratory day, week or periods')
            composite=json.dumps([course,project,kind],ensure_ascii=False,separators=(',',':'))
            course_id='lab:'+hashlib.sha256(composite.encode('utf-8')).hexdigest()
            room=' '.join(str(record.get('room_name') or '').split())
            identity=(course_id,week,day,start,end,room)
            if identity in seen: raise ValueError('Duplicate laboratory occurrence across pages')
            seen.add(identity)
            rows.append({'xnxq':config['term'],'kcdm':course_id,'kcmc':'【实验】'+course+' · '+project,
                         'skzc':str(week),'xq':'星期'+'一二三四五六日'[day-1],
                         'ksjc':str(start),'jsjc':str(end),'jxdd':room,
                         'teacher':str(record.get('teacher_name') or '').strip(),
                         'activityType':'laboratory','courseName':course,'projectName':project,
                         'selectionType':'自选' if kind==1 else '预置'})
    first=date.fromisoformat(config['week1_monday']); maximum=integer(config['maxWeekNumber'],'term weeks')
    base=config.get('school_custom',{}).get('lab_base','') if config.get('school_profile')=='custom' else ORIGIN
    snapshot={'source':base+PATH,'sourceAdapter':'lab-har','xnxq':config['term'],'fetchedAt':payload.get('capturedAt'),
              'beginDate':first.isoformat(),'endDate':(first+timedelta(weeks=maximum,days=-1)).isoformat(),
              'maxWeekNumber':maximum,'rows':rows,'pagesImported':sorted(pages),
              'identityBasis':'Composite hash of course, project, selection type; source has no verified stable ID'}
    if len(rows)!=next(iter(counts)): raise ValueError('Laboratory total row count mismatch')
    normalize(snapshot,config)
    return snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True); group.add_argument('--har'); group.add_argument('--response')
    parser.add_argument('--config',default='config.json'); parser.add_argument('--output',default='build/lab.snapshot.json')
    parser.add_argument('--sanitized-response-output'); parser.add_argument('--evidence-output')
    args=parser.parse_args()
    try:
        read=lambda p:json.loads(Path(p).read_text(encoding='utf-8-sig'))
        config=read(args.config)
        payload,evidence=load_har(read(args.har),config) if args.har else (read(args.response),{'liveReplayVerified':False})
        snapshot=convert(payload,config)
        if not snapshot['rows']: raise ValueError('Empty laboratory timetable; existing calendar retained')
        # Canonical sanitized fixture includes each page once, without HTTP headers.
        unique={p['request']['currpage']:p for p in payload['pages']}
        payload={**payload,'pages':[unique[n] for n in sorted(unique)]}
        evidence.update({'pagesImported':snapshot['pagesImported'],'occurrences':len(snapshot['rows'])})
        for path,value in [(args.sanitized_response_output,payload),(args.evidence_output,evidence),(args.output,snapshot)]:
            if path: atomic_write(path,json.dumps(value,ensure_ascii=False,indent=2))
        print(json.dumps({'state':'READY','adapter':'lab-har','pages':snapshot['pagesImported'],'occurrences':len(snapshot['rows'])}))
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'state':'DATA_INVALID','message':str(error)},ensure_ascii=False)); raise SystemExit(4)


if __name__=='__main__': main()
