"""Local administrator helper; never initializes Store or restarts sync jobs."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from koma.widget_api import WidgetAPI

class ExistingStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'komama.sqlite3'
        if not self.path.is_file():
            raise SystemExit('数据库不存在；先部署并创建 KOMA 用户')
    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys=ON')
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

def main():
    parser = argparse.ArgumentParser(description='生成/查看状态/撤销指定 KOMA 用户的小组件只读凭证')
    parser.add_argument('action', choices=('status','rotate','revoke'))
    parser.add_argument('--username', required=True)
    parser.add_argument('--data-dir', default=os.getenv('DATA_DIR','/data'))
    args = parser.parse_args()
    store = ExistingStore(args.data_dir)
    with store.db() as c:
        user = c.execute('SELECT id FROM users WHERE username=? AND disabled=0', (args.username,)).fetchone()
    if not user:
        raise SystemExit('用户不存在或已被停用')
    api = WidgetAPI(store)
    result = getattr(api, args.action)(user['id'])
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__': main()
