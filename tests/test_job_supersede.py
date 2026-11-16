import os
import subprocess
import sys
from pathlib import Path

SCRIPT = '''
from studio import db
db.init()
with db.connection() as c:
    c.execute("INSERT INTO projects (id,name,state,revision,created,updated) VALUES ('p','n','{}',0,0,0)")
old = db.job('p', 'guided_edit', {})
keep = db.job('p', 'ingest', {})
new = db.job('p', 'guided_edit', {})
with db.connection() as c:
    st = {r['id']: r['status'] for r in c.execute('SELECT id,status FROM jobs')}
assert st[old] == 'cancelled' and st[keep] == 'queued' and st[new] == 'queued', st
print('ok')
'''


def test_new_edit_supersedes_old_jobs(tmp_path):
    # 실행 중인 작업 처리기와 섞이지 않도록 별도 프로세스·별도 데이터 폴더에서 확인한다.
    env = {**os.environ, 'STUDIO_DATA_DIR': str(tmp_path), 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    done = subprocess.run([sys.executable, '-c', SCRIPT], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    assert done.returncode == 0 and 'ok' in done.stdout, done.stderr[-800:]
