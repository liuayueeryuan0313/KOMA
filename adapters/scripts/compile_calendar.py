"""Offline SDUT timetable normalizer and iCalendar compiler. Python 3.9+, stdlib only."""
import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
DAYS = {f'星期{d}': i for i, d in enumerate('一二三四五六日', 1)}


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_bytes(text.encode('utf-8'))
    os.replace(temporary, path)


def normalize(source, config):
    if config['timezone'] != 'Asia/Shanghai':
        raise ValueError('Only Asia/Shanghai is supported by this school adapter')
    first = date.fromisoformat(config['week1_monday'])
    if first.weekday() != 0 or source['beginDate'] != first.isoformat():
        raise ValueError('First Monday conflicts with source beginDate')
    if source['xnxq'] != config['term']:
        raise ValueError('New term detected; update configuration explicitly')
    if not config.get('calendar_id'):
        raise ValueError('A stable private calendar_id is required')
    maximum = int(source['maxWeekNumber'])
    if not 1 <= maximum <= 53:
        raise ValueError('Invalid maximum week')
    cancelled = set(config.get('cancel_dates', []))
    overrides = config.get('date_overrides', {})
    for value in cancelled | set(overrides) | set(overrides.values()):
        date.fromisoformat(value)
    result, seen = [], set()
    for row in source['rows']:
        if row['xnxq'] != source['xnxq']:
            raise ValueError('Mixed terms in response')
        week, weekday = int(row['skzc']), DAYS[row['xq']]
        p1, p2 = int(row['ksjc']), int(row['jsjc'])
        if not 1 <= week <= maximum or not 1 <= p1 <= p2:
            raise ValueError('Invalid course week or periods')
        block = config.get('period_ranges', {}).get(f'{p1}-{p2}')
        if block:
            start_text, end_text = block
        else:
            begin, end = config['periods'].get(str(p1)), config['periods'].get(str(p2))
            if not begin or not end:
                raise ValueError(f'Missing clock times for periods {p1}-{p2}')
            start_text, end_text = begin[0], end[1]
        start_clock, end_clock = time.fromisoformat(start_text), time.fromisoformat(end_text)
        if end_clock <= start_clock:
            raise ValueError('Class end must be later than start')
        original = first + timedelta(days=(week - 1) * 7 + weekday - 1)
        if original.isoformat() in cancelled:
            continue
        actual = date.fromisoformat(overrides.get(original.isoformat(), original.isoformat()))
        name = str(row['kcmc']).strip()
        if not name:
            raise ValueError('Empty course name')
        course_id = str(row.get('kcdm') or 'name:' + name)
        location = ' '.join(str(row.get('jxdd') or '').split())
        start = datetime.combine(actual, start_clock)
        end = datetime.combine(actual, end_clock)
        entry = {'term':source['xnxq'], 'courseId':course_id, 'name':name,
                 'week':week, 'weekday':weekday, 'originalDate':original.isoformat(),
                 'date':actual.isoformat(), 'startPeriod':p1, 'endPeriod':p2,
                 'startLocal':start.isoformat(), 'endLocal':end.isoformat(), 'location':location}
        for field in ['teacher','className','campus','activityType','courseName','projectName','selectionType']:
            if row.get(field):
                entry[field]=str(row[field])
        identity = (course_id, start.isoformat(), end.isoformat(), location)
        if identity in seen:
            raise ValueError('Duplicate course occurrence or override collision')
        seen.add(identity)
        result.append(entry)
    result.sort(key=lambda r:(r['startLocal'], r['courseId'], r['location']))
    return {'schemaVersion':1, 'term':source['xnxq'], 'timezone':'Asia/Shanghai',
            'week1Monday':first.isoformat(), 'sourceFetchedAt':source.get('fetchedAt'), 'occurrences':result}


def escape(value):
    return str(value).replace('\\','\\\\').replace('\r\n','\n').replace('\r','\n').replace('\n',r'\n').replace(';',r'\;').replace(',',r'\,')


def fold(line):
    lines, current = [], ''
    for char in line:
        if len((current + char).encode('utf-8')) > 75:
            lines.append(current)
            current = ' '
        current += char
    return '\r\n'.join(lines + [current])


def course_teacher(row, config):
    details=config.get('course_details',{}).get(row['courseId'],config.get('course_details',{}).get(row['name'],{}))
    return str(row.get('teacher') or details.get('teacher') or '').strip()


def display_location(row, config):
    return ' '.join(v for v in [row['location'],course_teacher(row,config)] if v)


def compile_calendar(normalized, config):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//SDUT Calendar Kit//1.0//ZH',
             'CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:'+escape(config.get('calendar_name','山东理工大学课表')),
             'X-WR-TIMEZONE:Asia/Shanghai','BEGIN:VTIMEZONE','TZID:Asia/Shanghai',
             'X-LIC-LOCATION:Asia/Shanghai','BEGIN:STANDARD','DTSTART:20200101T000000',
             'TZOFFSETFROM:+0800','TZOFFSETTO:+0800','TZNAME:CST','END:STANDARD','END:VTIMEZONE']
    groups = defaultdict(list)
    for row in normalized['occurrences']:
        key = (row['term'],row['courseId'],row['weekday'],row['startPeriod'],row['endPeriod'],row['location'])
        groups[key].append(row)
    recurring = 0
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda r:r['startLocal'])
        first = rows[0]
        starts = sorted({datetime.fromisoformat(r['startLocal']) for r in rows})
        start, end = starts[0], datetime.fromisoformat(first['endLocal'])
        uid_key = json.dumps([config['calendar_id'],*key], ensure_ascii=False, separators=(',',':'))
        uid = hashlib.sha256(uid_key.encode('utf-8')).hexdigest()+'@sdut-calendar-kit'
        weeks = ','.join(map(str,sorted({r['week'] for r in rows})))
        details = config.get('course_details',{}).get(first['courseId'],config.get('course_details',{}).get(first['name'],{}))
        description = f"第{first['startPeriod']}-{first['endPeriod']}节；教学周：{weeks}"
        teacher=course_teacher(first,config)
        if teacher:
            description += '\n教师：'+teacher
        if first.get('activityType')=='laboratory':
            description += '\n实验项目：'+first['projectName']+'\n安排类型：'+first['selectionType']
        if details.get('note'):
            description += '\n'+details['note']
        lines += ['BEGIN:VEVENT','UID:'+uid,'DTSTAMP:'+stamp,'LAST-MODIFIED:'+stamp,
                  'DTSTART;TZID=Asia/Shanghai:'+start.strftime('%Y%m%dT%H%M%S'),
                  'DTEND;TZID=Asia/Shanghai:'+end.strftime('%Y%m%dT%H%M%S'),
                  'SUMMARY:'+escape(first['name']),'LOCATION:'+escape(display_location(first,config)),
                  'DESCRIPTION:'+escape(description),'X-SDUT-COURSE-ID:'+escape(first['courseId'])]
        if len(starts)>1:
            interval = 2 if all((d-start).days % 14 == 0 for d in starts) else 1
            step = timedelta(weeks=interval)
            count = (starts[-1]-start).days//step.days+1
            baseline = {start+i*step for i in range(count)}
            lines.append(f'RRULE:FREQ=WEEKLY;INTERVAL={interval};COUNT={count}')
            for label, values in [('EXDATE',baseline-set(starts)),('RDATE',set(starts)-baseline)]:
                if values:
                    lines.append(label+';TZID=Asia/Shanghai:'+','.join(d.strftime('%Y%m%dT%H%M%S') for d in sorted(values)))
            recurring += 1
        lines += ['BEGIN:VALARM','ACTION:DISPLAY','TRIGGER;RELATED=START:-PT20M',
                  'DESCRIPTION:'+escape(first['name']+'@'+first['location']),
                  'END:VALARM','END:VEVENT']
    lines += ['END:VCALENDAR']
    ics = '\r\n'.join(fold(line) for line in lines)+'\r\n'
    validate_calendar(ics, normalized, config)
    return ics, {'seriesAndSingleEvents':len(groups),'weeklySeries':recurring,
                 'singleEvents':len(groups)-recurring,'occurrences':len(normalized['occurrences'])}


def unescape(value):
    result, i = [], 0
    while i < len(value):
        if value[i]=='\\' and i+1<len(value):
            i += 1
            result.append('\n' if value[i] in 'nN' else value[i])
        else:
            result.append(value[i])
        i += 1
    return ''.join(result)


def validate_calendar(ics, normalized, config):
    blob = ics.encode('utf-8')
    if b'\n' in blob.replace(b'\r\n',b'') or any(len(line)>75 for line in blob.split(b'\r\n')):
        raise ValueError('Invalid line endings or UTF-8 folding')
    text = ics.replace('\r\n ', '').replace('\r\n\t','')
    if 'BEGIN:VTIMEZONE\r\nTZID:Asia/Shanghai' not in text:
        raise ValueError('Timezone missing')
    actual, uids = Counter(), set()
    for part in text.split('BEGIN:VEVENT\r\n')[1:]:
        event=part.split('END:VEVENT')[0]
        if event.count('BEGIN:VALARM')!=1 or 'ACTION:DISPLAY\r\nTRIGGER;RELATED=START:-PT20M' not in event:
            raise ValueError('Missing or incorrect 20-minute reminder')
        props = dict(line.split(':',1) for line in event.split('BEGIN:VALARM')[0].split('\r\n') if ':' in line)
        if props['UID'] in uids:
            raise ValueError('Duplicate series UID')
        uids.add(props['UID'])
        def parse(value): return datetime.strptime(value,'%Y%m%dT%H%M%S')
        start = parse(props['DTSTART;TZID=Asia/Shanghai'])
        duration = parse(props['DTEND;TZID=Asia/Shanghai'])-start
        starts = {start}
        if 'RRULE' in props:
            rule = dict(item.split('=') for item in props['RRULE'].split(';'))
            if rule['FREQ'] != 'WEEKLY': raise ValueError('Unexpected recurrence type')
            step = timedelta(weeks=int(rule.get('INTERVAL','1')))
            starts = {start+i*step for i in range(int(rule['COUNT']))}
        for label, add in [('EXDATE',False),('RDATE',True)]:
            values = {parse(v) for v in props.get(label+';TZID=Asia/Shanghai','').split(',') if v}
            starts = starts | values if add else starts - values
        for value in starts:
            actual[(unescape(props['X-SDUT-COURSE-ID']),value.isoformat(),(value+duration).isoformat(),unescape(props['LOCATION']))] += 1
    expected = Counter((r['courseId'],r['startLocal'],r['endLocal'],display_location(r,config)) for r in normalized['occurrences'])
    if actual != expected:
        raise ValueError('Expanded calendar differs from normalized occurrences')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--config',default='config.json')
    parser.add_argument('--output',default='build/timetable.ics')
    parser.add_argument('--normalized-output')
    parser.add_argument('--allow-empty',action='store_true')
    args = parser.parse_args()
    try:
        source = json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
        config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
        normalized = normalize(source,config)
        if not normalized['occurrences'] and not args.allow_empty:
            raise ValueError('Empty term; retained existing calendar; explicit --allow-empty required')
        ics, metrics = compile_calendar(normalized,config)
        if args.normalized_output:
            atomic_write(args.normalized_output,json.dumps(normalized,ensure_ascii=False,indent=2))
        atomic_write(args.output,ics)
        print(json.dumps({'state':'PUBLISH_READY','output':args.output,'timezone':'Asia/Shanghai',**metrics}))
    except (ValueError,KeyError,TypeError,OSError) as error:
        print(json.dumps({'state':'BUILD_FAILED','message':str(error)},ensure_ascii=False))
        raise SystemExit(4)


if __name__=='__main__':
    main()
