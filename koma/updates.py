"""Read-only checks against KOMA's latest public GitHub release."""
import json
import re
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .app_version import VERSION

REPOSITORY = 'liuayueeryuan0313/KOMA'
RELEASES_URL = 'https://github.com/' + REPOSITORY + '/releases'
LATEST_API = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
SEMVER = re.compile(r'[vV]?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')


def parse_version(value):
    if not isinstance(value,str) or len(value)>100: raise ValueError('版本号格式无效')
    match=SEMVER.fullmatch(value)
    if not match: raise ValueError('版本号格式无效')
    pre=match[4].split('.') if match[4] else []
    if any(p.isdigit() and len(p)>1 and p[0]=='0' for p in pre):raise ValueError('版本号格式无效')
    return tuple(int(match[i]) for i in (1,2,3)),pre


def is_newer(latest,current):
    left,lp=parse_version(latest);right,rp=parse_version(current)
    if left!=right:return left>right
    if not lp or not rp:return bool(rp) and not lp
    for a,b in zip(lp,rp):
        if a==b:continue
        if a.isdigit() and b.isdigit():return int(a)>int(b)
        if a.isdigit()!=b.isdigit():return not a.isdigit()
        return a>b
    return len(lp)>len(rp)


class UpdateChecker:
    def __init__(self,current=VERSION,opener=None,clock=None):
        self.current=current;self.opener=opener or urlopen;self.clock=clock or time.monotonic
        self.lock=threading.Lock();self.result=None;self.expires=0
    def check(self):
        with self.lock:
            if self.result and self.clock()<self.expires:return {**self.result,'cached':True}
            result={'current_version':self.current,'release_url':RELEASES_URL,
                    'checked_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'cached':False}
            try:
                request=Request(LATEST_API,headers={'Accept':'application/vnd.github+json','User-Agent':'KOMA/'+self.current,'X-GitHub-Api-Version':'2026-03-10'})
                with self.opener(request,timeout=8) as response:
                    payload=response.read(262145)
                if len(payload)>262144:raise ValueError('更新响应过大')
                release=json.loads(payload)
                if not isinstance(release,dict) or release.get('draft') or release.get('prerelease'):raise ValueError('不是正式发布版本')
                tag=release.get('tag_name');parse_version(tag)
                result.update(status='available' if is_newer(tag,self.current) else 'current',latest_version=tag.lstrip('vV'),release_url=RELEASES_URL+'/tag/'+quote(tag,safe=''))
            except HTTPError as error:
                if error.code==404:result.update(status='unavailable',message='尚未找到公开正式版本，暂时无法比较。')
                elif error.code in (403,429):result.update(status='error',message='GitHub 请求受限，请稍后重试。')
                else:result.update(status='error',message='GitHub 暂时不可用，请稍后重试。')
            except (URLError,TimeoutError,OSError):result.update(status='error',message='无法连接 GitHub，请检查网络后重试。')
            except (ValueError,TypeError,UnicodeError):result.update(status='error',message='更新信息格式无效，暂时无法比较版本。')
            self.result=result;self.expires=self.clock()+(300 if result['status'] in ('current','available') else 30)
            return dict(result)
