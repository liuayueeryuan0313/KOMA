"""Per-user school endpoints. Changing a destination invalidates school secrets."""
import copy
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS=json.loads((Path(__file__).parent/'adapters/school-defaults.json').read_text(encoding='utf-8'))
URL_FIELDS=('app_origin','app_h5_base','jw_base','lab_base','sso_base')

def validate_url(value,field):
    if not isinstance(value,str) or len(value)>500:raise ValueError('学校地址格式无效')
    if not value:return ''
    if re.search(r'[\s\\\x00-\x1f]',value):raise ValueError('学校地址不能包含空格或反斜杠')
    try:
        parts=urlsplit(value);host=parts.hostname;port=parts.port
    except ValueError:raise ValueError('学校地址或端口格式无效') from None
    allowed=('http','https') if field=='app_origin' else ('https',)
    if parts.scheme not in allowed or not host or parts.username is not None or parts.password is not None or parts.query or parts.fragment:raise ValueError('请填写学校完整地址；除 App 旧版接口外须使用 HTTPS，不能带账号、查询参数或片段')
    try:
        address=ipaddress.ip_address(host)
    except ValueError:
        if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?',host) or '.' not in host or host.lower().endswith(('.localhost','.local','.internal')):raise ValueError('请填写学校的公开域名')
    else:
        if not address.is_global:raise ValueError('学校地址不能指向本机、内网或保留地址')
    if field=='app_origin' and parts.path not in ('','/'):raise ValueError('App 服务地址只填写协议、域名和端口')
    if '%' in parts.path or any(segment in ('.','..') for segment in parts.path.split('/')):raise ValueError('学校接口路径无效')
    return value.rstrip('/')

def prepare_school_config(config,data):
    result=copy.deepcopy(config)
    selected=data.get('school_profile',result.get('school_profile','sdut'))
    if selected not in ('sdut','custom'):raise ValueError('请选择山东理工大学或自定义学校')
    custom=result.get('school_custom',{})
    if 'school_custom' in data:
        entered=data['school_custom']
        if not isinstance(entered,dict) or set(entered)-set(DEFAULTS):raise ValueError('自定义学校参数无效')
        custom={**custom,**entered}
    normalized={}
    for key,value in custom.items():
        if not isinstance(value,str) or len(value)>500:raise ValueError('学校参数格式无效')
        value=value.strip()
        if key in URL_FIELDS:value=validate_url(value,key)
        elif key in ('app_exchange_path','lab_cas_entry'):
            if value and (not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+',value) or any(segment in ('.','..') for segment in value.split('/'))):raise ValueError('接口路径应以 / 开头，不能包含域名、查询参数或上级目录')
        elif key!='name' and value and not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}',value):raise ValueError('学校代码、应用编号或版本格式无效')
        if key=='name' and (len(value)>80 or any(ord(c)<32 for c in value)):raise ValueError('学校名称格式无效')
        normalized[key]=value
    if selected=='custom' and not normalized.get('name'):raise ValueError('请填写自定义学校名称')
    result.update(school_profile=selected,school_custom=normalized)
    return result

def effective_school(config):
    if config.get('school_profile','sdut')=='sdut':return copy.deepcopy(DEFAULTS)
    # Blank unused platforms stay blank; never fall back to another school's host.
    base={key:('' if key in URL_FIELDS or key in ('name','app_school_id','app_yyid') else value) for key,value in DEFAULTS.items()}
    return {**base,**config.get('school_custom',{})}

def school_changed(before,after):
    old=effective_school(before);new=effective_school(after)
    return {k:v for k,v in old.items() if k!='name'}!={k:v for k,v in new.items() if k!='name'}

def prepare_clock_config(config,data):
    result=copy.deepcopy(config)
    if 'period_times' not in data:return result
    value=data['period_times']
    if not isinstance(value,str) or len(value)>4000:raise ValueError('作息时间格式无效')
    periods={};ranges={}
    for line in value.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'\s*(\d{1,2}(?:-\d{1,2})?)\s+([0-2]\d:[0-5]\d)\s+([0-2]\d:[0-5]\d)\s*',line)
        if not match:raise ValueError('每行按“节次 开始时间 结束时间”填写，例如 1 08:00 08:45')
        key,start,end=match.groups();numbers=[int(x) for x in key.split('-')]
        if any(not 1<=x<=40 for x in numbers) or numbers!=sorted(numbers) or start>=end or start[:2]>'23' or end[:2]>'23':raise ValueError('作息节次或起止时间无效')
        target=ranges if '-' in key else periods
        if key in target:raise ValueError('作息时间存在重复节次')
        target[key]=[start,end]
    if not periods and not ranges:raise ValueError('请填写本校作息时间')
    result['periods']=periods;result['period_ranges']=ranges
    return result
