import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .settings import DATA


def uid():
    return uuid.uuid4().hex


@contextmanager
def connection():
    db = sqlite3.connect(DATA / 'studio.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def init():
    with connection() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, revision INTEGER NOT NULL,
          state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS assets (
          id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
          name TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
          metadata TEXT NOT NULL DEFAULT '{}', analysis TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS chunks (
          asset_id TEXT NOT NULL REFERENCES assets(id), idx INTEGER NOT NULL,
          size INTEGER NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(asset_id,idx));
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, project_id TEXT REFERENCES projects(id), kind TEXT NOT NULL,
          status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
          payload TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', cancel INTEGER NOT NULL DEFAULT 0,
          created REAL NOT NULL, updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL);
        ''')


def job(project_id, kind, payload):
    ident = uid()
    with connection() as db:
        db.execute('INSERT INTO jobs (id,project_id,kind,status,payload,created,updated) VALUES (?,?,?,?,?,?,?)',
                   (ident, project_id, kind, 'queued', json.dumps(payload, ensure_ascii=False), time.time(), time.time()))
    return ident


def update_job(ident, **fields):
    if 'result' in fields:
        fields['result'] = json.dumps(fields['result'], ensure_ascii=False)
    fields['updated'] = time.time()
    with connection() as db:
        db.execute('UPDATE jobs SET ' + ','.join(f'{key}=?' for key in fields) + ' WHERE id=?',
                   (*fields.values(), ident))


def get_asset(ident):
    with connection() as db:
        row = db.execute('SELECT * FROM assets WHERE id=?', (ident,)).fetchone()
    if not row:
        raise ValueError('원본 파일을 찾을 수 없습니다.')
    result = dict(row)
    for key in ['metadata', 'analysis']:
        result[key] = json.loads(result[key])
    return result
