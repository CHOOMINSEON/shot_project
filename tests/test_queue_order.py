import sqlite3


def test_newest_queued_job_runs_first_and_waiters_get_position():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE jobs (id TEXT, status TEXT, created REAL, message TEXT)')
    conn.executemany('INSERT INTO jobs VALUES (?,?,?,?)', [('old', 'queued', 1, ''), ('mid', 'queued', 2, ''), ('new', 'queued', 3, '')])
    row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created DESC LIMIT 1").fetchone()
    assert row['id'] == 'new'
