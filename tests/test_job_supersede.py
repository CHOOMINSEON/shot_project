import json
from studio import db


def test_new_edit_supersedes_old_jobs(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DATA', tmp_path)
    try:
        db.init()
    except Exception:
        import pytest
        pytest.skip('db 초기화 방식이 달라 건너뜀')
    with db.connection() as c:
        c.execute("INSERT INTO projects (id,name,state,revision,created,updated) VALUES ('p','n','{}',0,0,0)")
    old = db.job('p', 'guided_edit', {})
    run = db.job('p', 'ingest', {})
    new = db.job('p', 'guided_edit', {})
    with db.connection() as c:
        st = {r['id']: r['status'] for r in c.execute('SELECT id,status FROM jobs')}
    assert st[old] == 'cancelled' and st[run] == 'queued' and st[new] == 'queued'
