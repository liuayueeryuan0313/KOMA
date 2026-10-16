"""Source version and image build timestamp, recorded once at build time."""
import json
import os
from datetime import datetime,timezone
from pathlib import Path

VERSION='0.4.0'
BUILD_INFO_PATH=Path(__file__).with_name('build-info.json')


def normalize_build_date(value):
    if not isinstance(value,str) or 'T' not in value:raise ValueError('Build date must be an ISO 8601 timestamp')
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:raise ValueError('Build date must include a time zone')
    return parsed.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')


def read_build_date(path=BUILD_INFO_PATH):
    try:
        info=json.loads(Path(path).read_text())
        if not isinstance(info,dict) or info.get('version')!=VERSION:return None
        return normalize_build_date(info.get('build_date'))
    except (OSError,ValueError,TypeError):return None


def write_build_info(path=BUILD_INFO_PATH,timestamp=None):
    timestamp=timestamp or os.getenv('KOMA_BUILD_DATE') or datetime.now(timezone.utc).isoformat()
    info={'version':VERSION,'build_date':normalize_build_date(timestamp)}
    Path(path).write_text(json.dumps(info)+'\n')
    return info


BUILD_DATE=read_build_date()
