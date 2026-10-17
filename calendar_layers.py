"""School snapshots plus per-user, per-term manual overlays."""
import json
import secrets
from collections import defaultdict
from datetime import date, timedelta

from core import digest, json_text, now
from adapters.scripts.compile_calendar import normalize, compile_calendar, course_teacher

TIME_FIELDS = ('week', 'weekday', 'startPeriod', 'endPeriod')
TEXT_FIELDS = ('name', 'location', 'teacher', 'courseName', 'projectName')


def revision(row):
    return digest(json_text(row))


def _identity(row):
    return (row['courseId'], row['originalDate'], row['startPeriod'], row['endPeriod'], row.get('className', ''))


def _unique_matches(old, new, key, matched):
    left, right = defaultdict(list), defaultdict(list)
    used = set(matched.values())
    for identifier, row in old.items():
        if identifier not in used:
            value = key(row)
            if value is not None: left[value].append(identifier)
    for i, row in enumerate(new):
        if i not in matched:
            value = key(row)
            if value is not None: right[value].append(i)
    for value in left.keys() & right.keys():
        if len(left[value]) == len(right[value]) == 1:
            oi,ni=left[value][0],right[value][0]
            a,b=old[oi].get('sourceOccurrenceId'),new[ni].get('sourceOccurrenceId')
            if a and b and a!=b:continue
            matched[ni] = oi


def register_school(c, user_id, kind, normalized):
    term = normalized['term']
    records = c.execute('SELECT identifier,row FROM school_occurrences WHERE user_id=? AND kind=? AND term=?', (user_id, kind, term)).fetchall()
    old = {r['identifier']: json.loads(r['row']) for r in records}
    incoming = normalized['occurrences']
    matched = {}
    # Only an explicitly supplied per-occurrence upstream identifier is trusted.
    # Lab row_id and JW kch_id are not assumed to be stable scheduling IDs.
    _unique_matches(old, incoming, lambda r: ('upstream', r['sourceOccurrenceId']) if r.get('sourceOccurrenceId') else None, matched)
    _unique_matches(old, incoming, _identity, matched)
    # A uniquely moved lesson is recognizable without relying on display name.
    _unique_matches(old, incoming, lambda r: (r['courseId'], r['week'], r.get('className', '')) if not r['courseId'].startswith('name:') else None, matched)
    _unique_matches(old, incoming, lambda r: (r['courseId'], r.get('className', '')) if not r['courseId'].startswith('name:') else None, matched)
    c.execute('UPDATE school_occurrences SET active=0 WHERE user_id=? AND kind=? AND term=?', (user_id, kind, term))
    for i, row in enumerate(incoming):
        identifier = matched.get(i) or secrets.token_hex(32)
        c.execute('INSERT OR REPLACE INTO school_occurrences VALUES(?,?,?,?,?,1)', (user_id, kind, term, identifier, json_text(row)))


def ensure_layers(c, user_id, kind, config):
    term = config['term']
    if c.execute('SELECT 1 FROM school_sources WHERE user_id=? AND kind=? AND term=?', (user_id, kind, term)).fetchone(): return
    cal = c.execute('SELECT * FROM calendars WHERE user_id=? AND kind=?', (user_id, kind)).fetchone()
    first = date.fromisoformat(config['week1_monday'])
    snapshot = dict(xnxq=term, beginDate=first.isoformat(), endDate=(first + timedelta(weeks=config['maxWeekNumber'], days=-1)).isoformat(), maxWeekNumber=config['maxWeekNumber'], sourceAdapter='manual', rows=[])
    if cal and json.loads(cal['normalized'])['term'] == term:
        saved = json.loads(cal['snapshot'])
        if 'rows' in saved:
            snapshot = {**saved, 'rows': [r for r in saved['rows'] if not r.get('manual')]}
            # The initial editor overwrote raw rows. Preserve these as standalone
            # manual entries; no original school record can safely be invented.
            for raw in saved['rows']:
                if raw.get('manual'):
                    rows = normalize({**saved, 'rows': [raw]}, config)['occurrences']
                    for row in rows:
                        identifier = digest('legacy:' + kind + ':' + row['courseId'] + ':' + row['startLocal'])
                        c.execute('INSERT OR IGNORE INTO manual_occurrences VALUES(?,?,?,?,?,?,?)', (user_id, kind, term, identifier, 'create', json_text(row), '{}'))
    normalized = normalize(snapshot, config)
    c.execute('INSERT INTO school_sources VALUES(?,?,?,?,?)', (user_id, kind, term, json_text(snapshot), json_text(normalized)))
    register_school(c, user_id, kind, normalized)


def apply_fields(base, fields, config):
    row = {**base, **fields}
    if any(field in fields for field in TIME_FIELDS):
        first = date.fromisoformat(config['week1_monday'])
        raw = dict(xnxq=config['term'], kcdm=row['courseId'], kcmc=row['name'], skzc=str(row['week']), xq='星期' + '一二三四五六日'[row['weekday']-1], ksjc=str(row['startPeriod']), jsjc=str(row['endPeriod']), jxdd=row.get('location', ''))
        snapshot = dict(xnxq=config['term'], beginDate=first.isoformat(), maxWeekNumber=config['maxWeekNumber'], rows=[raw])
        result = normalize(snapshot, config)['occurrences']
        if not result: raise ValueError('该日期已在学期配置中取消，请选择其他日期')
        for field in ('originalDate','date','startLocal','endLocal'):
            row[field] = result[0][field]
    return row


def effective_rows(c, user_id, kind, config):
    term = config['term']
    school = {r['identifier']: (json.loads(r['row']), bool(r['active'])) for r in c.execute('SELECT * FROM school_occurrences WHERE user_id=? AND kind=? AND term=?', (user_id, kind, term))}
    edits = {r['identifier']: dict(r) for r in c.execute('SELECT * FROM manual_occurrences WHERE user_id=? AND kind=? AND term=?', (user_id, kind, term))}
    deleted = {r['identifier'] for r in c.execute('SELECT identifier FROM deleted_occurrences WHERE user_id=? AND kind=? AND term=?', (user_id, kind, term))}
    output = []
    for identifier in school.keys() | edits.keys():
        if identifier in deleted: continue
        base, active = school.get(identifier, ({}, False))
        edit = edits.get(identifier)
        if not active and not edit: continue
        fields, conflicts, origin = {}, [], 'school'
        latest = dict(base)
        if base:latest['teacher']=course_teacher(base,config)
        if edit:
            saved, fields = json.loads(edit['baseline']), json.loads(edit['fields'])
            if edit['mode'] == 'create':
                row, origin = saved, 'manual'
            else:
                origin = 'override'
                reference = dict(base if active else saved)
                if active:
                    reference['teacher'] = course_teacher(reference, config)
                    for field in fields:
                        if reference.get(field, '') != saved.get(field, '') and reference.get(field, '') != fields[field]:
                            conflicts.append(field)
                elif not saved.get('_ack_missing'):
                    conflicts.append('missing')
                row = apply_fields(reference, fields, config)
        else:
            row = dict(base)
        row['teacher'] = row.get('teacher', '') if edit and (edit['mode'] == 'create' or 'teacher' in fields) else course_teacher(row, config)
        row = {**row, 'occurrenceId': identifier, 'origin': origin, 'conflictFields': conflicts,
               'schoolMissing': origin == 'override' and not active,
               'schoolArrangement': latest if origin == 'override' and active else None}
        if edit:
            row['eventUid'] = digest(user_id + ':' + kind + ':' + identifier) + '@koma'
        row['revision'] = revision(row)
        output.append(row)
    return sorted(output, key=lambda r: (r['startLocal'], r['courseId'], r['occurrenceId']))


def rebuild(c, user_id, config):
    kinds, combined = {}, []
    for kind in ('teaching','lab'):
        ensure_layers(c, user_id, kind, config)
        source = c.execute('SELECT * FROM school_sources WHERE user_id=? AND kind=? AND term=?', (user_id, kind, config['term'])).fetchone()
        normalized = json.loads(source['normalized'])
        normalized['occurrences'] = effective_rows(c, user_id, kind, config)
        kinds[kind] = (json.loads(source['snapshot']), normalized)
        combined.extend(normalized['occurrences'])
    for row in combined:
        row['timeOverlap']=any(row is not other and row['startLocal']<other['endLocal'] and other['startLocal']<row['endLocal'] for other in combined)
    aggregate = {**kinds['teaching'][1], 'occurrences': sorted(combined, key=lambda r: (r['startLocal'], r['courseId']))}
    for kind, (snapshot, normalized) in [*kinds.items(), ('combined', ({'sourceAdapter':'layered'}, aggregate))]:
        # Keep an absent source unavailable until it contains school or manual rows.
        if kind != 'combined' and not normalized['occurrences'] and not snapshot['rows']:
            c.execute('DELETE FROM calendars WHERE user_id=? AND kind=?', (user_id, kind)); continue
        ics, metrics = compile_calendar(normalized, config)
        rows = normalized['occurrences']
        metrics.update(term=config['term'], conflicts=sum(bool(r['conflictFields']) for r in rows))
        if kind == 'combined':
            metrics['overlaps'] = sum(a['startLocal'] < b['endLocal'] and b['startLocal'] < a['endLocal'] for i,a in enumerate(rows) for b in rows[i+1:])
        c.execute('INSERT OR REPLACE INTO calendars VALUES(?,?,?,?,?,?,?,?)', (user_id,kind,ics,digest(ics),json_text(snapshot),json_text(normalized),json_text(metrics),now()))


def publish_school(store, user_id, kind, snapshot, normalized):
    config = store.settings(user_id)['config']
    if normalized['term'] != config['term']: raise ValueError('学期已变更，请重新同步')
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        ensure_layers(c, user_id, kind, config)
        register_school(c, user_id, kind, normalized)
        c.execute('INSERT OR REPLACE INTO school_sources VALUES(?,?,?,?,?)', (user_id,kind,config['term'],json_text(snapshot),json_text(normalized)))
        rebuild(c, user_id, config)


def assert_editable(c, user_id):
    if c.execute("SELECT 1 FROM sync_state WHERE user_id=? AND state IN ('running','queued')", (user_id,)).fetchone():
        raise ValueError('同步进行中，请完成后再编辑课表')


def resolve_occurrence(store, user_id, kind, identifier, action, expected_revision=None):
    config = store.settings(user_id)['config']
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE'); assert_editable(c, user_id)
        ensure_layers(c, user_id, kind, config)
        row = next((r for r in effective_rows(c,user_id,kind,config) if r['occurrenceId']==identifier), None)
        if not row or row['origin'] != 'override': raise ValueError('该课程没有可恢复的学校安排')
        if expected_revision and expected_revision != row['revision']: raise ValueError('课程已变更，请刷新后重新操作')
        if action == 'restore':
            c.execute('DELETE FROM manual_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=?', (user_id,kind,config['term'],identifier))
        elif action == 'keep':
            existing = c.execute('SELECT baseline FROM manual_occurrences WHERE user_id=? AND kind=? AND term=? AND identifier=?', (user_id,kind,config['term'],identifier)).fetchone()
            baseline = row['schoolArrangement'] or {**json.loads(existing['baseline']), '_ack_missing':True}
            baseline['teacher'] = course_teacher(baseline, config)
            c.execute('UPDATE manual_occurrences SET baseline=? WHERE user_id=? AND kind=? AND term=? AND identifier=?', (json_text(baseline),user_id,kind,config['term'],identifier))
        else: raise ValueError('无效冲突处理方式')
        rebuild(c,user_id,config)
        c.execute('INSERT INTO logs(user_id,kind,category,level,event,message,created_at) VALUES(?,?,?,?,?,?,?)', (user_id,kind,'sync','info','MANUAL_RESOLVED','已恢复学校安排' if action=='restore' else '已确认保留手动修改',now()))


def migrate_legacy(store):
    """Upgrade old cached views before exposing their new stable editing IDs."""
    with store.db() as c:
        c.execute('BEGIN IMMEDIATE')
        for settings in c.execute('SELECT user_id,config FROM settings').fetchall():
            config=json.loads(settings['config'])
            calendars=c.execute("SELECT normalized FROM calendars WHERE user_id=? AND kind IN ('teaching','lab')",(settings['user_id'],)).fetchall()
            needs_upgrade=False
            for calendar in calendars:
                normalized=json.loads(calendar['normalized'])
                if normalized['term']==config['term'] and normalized['week1Monday']==config['week1_monday']:
                    needs_upgrade=needs_upgrade or any('origin' not in row or 'occurrenceId' not in row for row in normalized['occurrences'])
            if needs_upgrade:rebuild(c,settings['user_id'],config)
