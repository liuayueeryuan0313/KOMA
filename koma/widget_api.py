"""Persistent, per-user, read-only timetable credentials for desktop widgets."""
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

CHINA = timezone(timedelta(hours=8))


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def project_name(row, kind):
    name = str(row.get('name') or '').strip()
    if kind != 'lab':
        return name
    project = str(row.get('projectName') or '').strip()
    if project:
        return project
    name = re.sub(r'^\s*(?:\[实验\]|【实验】)\s*', '', name)
    parts = re.split(r'\s*[·•|｜]\s*|\s+[—–-]\s+', name)
    return ' · '.join(parts[1:]).strip() if len(parts) > 1 else name


def local_time(value):
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=CHINA) if parsed.tzinfo is None else parsed.astimezone(CHINA)


class WidgetAPI:
    def __init__(self, store):
        self.store = store
        with store.db() as connection:
            connection.execute('''CREATE TABLE IF NOT EXISTS widget_tokens(
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)''')

    def status(self, user_id):
        with self.store.db() as connection:
            row = connection.execute('SELECT created_at FROM widget_tokens WHERE user_id=?', (user_id,)).fetchone()
        return {'configured': bool(row), 'createdAt': row['created_at'] if row else None,
                'scope': 'timetable:read', 'expiresAt': None}

    def rotate(self, user_id):
        token, created = 'kw_' + secrets.token_urlsafe(32), stamp()
        with self.store.db() as connection:
            connection.execute('INSERT OR REPLACE INTO widget_tokens VALUES(?,?,?)',
                               (user_id, hashlib.sha256(token.encode()).hexdigest(), created))
        return {'token': token, 'createdAt': created, 'scope': 'timetable:read', 'expiresAt': None}

    def revoke(self, user_id):
        with self.store.db() as connection:
            connection.execute('DELETE FROM widget_tokens WHERE user_id=?', (user_id,))
        return {'configured': False}

    def authenticate(self, authorization):
        if not isinstance(authorization, str) or len(authorization) > 128:
            return None
        match = re.fullmatch(r'Bearer[ \t]+(kw_[A-Za-z0-9_-]{43})', authorization, re.I)
        if not match:
            return None
        digest = hashlib.sha256(match[1].encode()).hexdigest()
        with self.store.db() as connection:
            row = connection.execute('''SELECT users.id FROM widget_tokens
                JOIN users ON users.id=widget_tokens.user_id
                WHERE token_hash=? AND users.disabled=0''', (digest,)).fetchone()
        return row['id'] if row else None

    def timetable(self, user_id, query='', *, today=None):
        params = parse_qs(query, keep_blank_values=True)
        if set(params) - {'days', 'offset'} or any(len(v) != 1 for v in params.values()):
            raise ValueError('只允许 days 和 offset 参数；凭证请放在 Authorization 请求头')
        try:
            days, offset = int(params.get('days', ['3'])[0]), int(params.get('offset', ['0'])[0])
        except (ValueError, TypeError):
            raise ValueError('days 与 offset 须为整数') from None
        if not 1 <= days <= 7 or not -365 <= offset <= 365:
            raise ValueError('days 范围 1–7；offset 范围 -365–365，单位为天')
        start = (today or datetime.now(CHINA).date()) + timedelta(days=offset)
        end = start + timedelta(days=days)
        sources, courses = {}, []
        # Read a consistent database snapshot without loading school credentials or logs.
        with self.store.db() as connection:
            connection.execute('BEGIN')
            settings = connection.execute('SELECT config FROM settings WHERE user_id=?', (user_id,)).fetchone()
            if not settings:
                raise ValueError('账户配置不存在')
            config = json.loads(settings['config'])
            states = {r['kind']: dict(r) for r in connection.execute(
                'SELECT kind,state,last_success FROM sync_state WHERE user_id=?', (user_id,))}
            for kind in ('teaching', 'lab'):
                cal = connection.execute('SELECT normalized,updated_at FROM calendars WHERE user_id=? AND kind=?', (user_id, kind)).fetchone()
                state = states.get(kind, {})
                sources[kind] = {'available': bool(cal), 'updatedAt': cal['updated_at'] if cal else None,
                                 'lastSuccess': state.get('last_success'), 'syncState': state.get('state', 'idle')}
                if not cal:
                    continue
                for row in json.loads(cal['normalized']).get('occurrences', []):
                    begin, finish = local_time(row['startLocal']), local_time(row['endLocal'])
                    if not start <= begin.date() < end:
                        continue
                    name = project_name(row, kind)
                    courses.append({'id': row.get('occurrenceId') or hashlib.sha256(
                        (kind + ':' + str(row.get('courseId', '')) + ':' + begin.isoformat() + ':' + str(row.get('location', ''))).encode()).hexdigest(),
                        'kind': kind, 'name': name, 'projectName': name if kind == 'lab' else None,
                        'location': str(row.get('location') or ''), 'date': begin.date().isoformat(),
                        'startAt': begin.isoformat(timespec='seconds'), 'endAt': finish.isoformat(timespec='seconds'),
                        'startPeriod': row.get('startPeriod'), 'endPeriod': row.get('endPeriod')})
        courses.sort(key=lambda c: (c['startAt'], c['kind'], c['id']))
        for course in courses:
            course['timeOverlap'] = any(other is not course and other['startAt'] < course['endAt']
                                        and other['endAt'] > course['startAt'] for other in courses)
        first = datetime.fromisoformat(config['week1_monday']).date()
        columns = []
        for i in range(days):
            day = start + timedelta(days=i)
            columns.append({'date': day.isoformat(), 'weekday': day.isoweekday(),
                            'teachingWeek': (day - first).days // 7 + 1,
                            'courses': [c for c in courses if c['date'] == day.isoformat()]})
        available = sum(s['available'] for s in sources.values())
        return {'schemaVersion': 1, 'generatedAt': stamp(), 'timezone': 'Asia/Shanghai',
                'state': 'ok' if available == 2 else 'partial' if available else 'unavailable',
                'range': {'startDate': start.isoformat(), 'endDate': (end - timedelta(days=1)).isoformat(), 'days': days},
                'term': {'name': config['term'], 'firstMonday': first.isoformat(), 'maxWeeks': config.get('maxWeekNumber')},
                'sources': sources, 'days': columns}
