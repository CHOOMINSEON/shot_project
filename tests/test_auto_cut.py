import json
import subprocess

import pytest

from studio import db, timeline, worker
from studio.media import probe
from test_app import upload_video, wait_job


def start(owner, project, asset_id, **options):
    return owner.post(f'/api/projects/{project["id"]}/auto-cut', json={
        'revision': project['revision'], 'asset_id': asset_id, **options})


def test_acoustic_silence_applies_without_model_and_renders_shorter_mp4(owner, sample, tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'load_model', lambda *args: pytest.fail('Silence cut must not need a speech model'))
    p, asset_id = upload_video(owner, sample)
    response = start(owner, p, asset_id)
    assert response.status_code == 200, response.text
    job = wait_job(owner, response.json()['job_id'])
    assert job['status'] == 'completed', job['message']
    result = job['result']
    assert result['applied'] and 1.3 < result['removed_seconds'] < 2
    current = owner.get('/api/projects/' + p['id']).json()
    # Audible non-speech sine is retained; a speech-only VAD would delete it.
    assert 6 < current['duration'] < 6.8
    assert len(current['state']['clips']) == 2
    assert current['state']['clips'][0]['end'] > 2
    assert current['state']['clips'][1]['start'] < 4
    assert len(current['assets'][0]['analysis']['silence']['gaps']) == 1
    video = result['files'][0]
    path = tmp_path / 'actual-preview.mp4'
    response = owner.get(f'/api/exports/{job["id"]}/{video["name"]}')
    assert response.status_code == 200
    path.write_bytes(response.content)
    assert abs(probe(path)['duration'] - current['duration']) < .08
    # A resumed job reuses the committed timeline, not a second cut application.
    with db.connection() as conn:
        payload = json.loads(conn.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()['payload'])
    worker.auto_cut(job['id'], payload)
    assert owner.get('/api/projects/' + p['id']).json()['revision'] == current['revision']
    undone = owner.post(f'/api/projects/{p["id"]}/auto-cut/{job["id"]}/undo', json={'revision': current['revision']})
    assert undone.status_code == 200
    assert undone.json()['state'] == p['state']
    assert undone.json()['duration'] == 8


def test_silence_cut_respects_protection_and_preserves_existing_caption_edits(owner, sample):
    p, asset_id = upload_video(owner, sample)
    state = p['state']
    state['protections'] = [{'asset_id': asset_id, 'start': 2.5, 'end': 3}]
    state['captions'] = {'signature': timeline.signature(state), 'items': [
        {'id': 'manual', 'start': 5, 'end': 6, 'text': '확인한 제품명 · 안 달아요', 'edited': True}]}
    p = owner.put('/api/projects/' + p['id'], json={'revision': p['revision'], 'name': p['name'], 'state': state}).json()
    job = wait_job(owner, start(owner, p, asset_id).json()['job_id'])
    assert job['status'] == 'completed', job['message']
    current = owner.get('/api/projects/' + p['id']).json()
    assert any(c['start'] <= 2.5 and c['end'] >= 3 for c in current['state']['clips'])
    assert current['state']['captions']['items'][0]['text'] == '확인한 제품명 · 안 달아요'
    assert current['state']['captions']['signature'] == current['signature']
    assert current['state']['captions']['items'][0]['start']<5
    assert not current['state']['captions']['items'][0].get('reviewed')
    # Preview is usable; final captions still require timing correction/review.
    assert job['result']['files']
    assert owner.post('/api/projects/' + p['id'] + '/render', json={'revision': current['revision']}).status_code == 422


def test_silence_job_never_overwrites_concurrent_edits(owner, sample):
    p, asset_id = upload_video(owner, sample)
    payload = {'revision': p['revision'], 'asset_id': asset_id, 'threshold_db': -40,
               'minimum': .6, 'before': .12, 'after': .2}
    # Simulate a persisted request made before another tab saves an edit.
    changed = owner.put('/api/projects/' + p['id'], json={
        'revision': p['revision'], 'name': '다른 탭 변경', 'state': p['state']}).json()
    ident = db.job(p['id'], 'auto_cut', payload)
    job = wait_job(owner, ident)
    assert job['status'] == 'failed' and '변경' in job['message']
    current = owner.get('/api/projects/' + p['id']).json()
    assert current['revision'] == changed['revision'] and current['duration'] == 8
    assert start(owner, p, asset_id).status_code == 409
    assert start(owner, changed, asset_id, threshold_db="Infinity").status_code == 422


@pytest.mark.parametrize('audio', [False, True])
def test_no_audio_or_all_silent_never_deletes_entire_video(owner, tmp_path, audio):
    path = tmp_path / 'silent.mp4'
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=2']
    if audio:
        command += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '2', '-c:a', 'aac']
    command += ['-c:v', 'libx264', '-threads', '2', str(path)]
    subprocess.run(command, check=True)
    p, asset_id = upload_video(owner, path)
    response = start(owner, p, asset_id)
    if audio:
        job = wait_job(owner, response.json()['job_id'])
        assert job['status'] == 'failed' and '전체가 무음' in job['message']
    else:
        assert response.status_code == 422 and '오디오' in response.json()['detail']
    current = owner.get('/api/projects/' + p['id']).json()
    assert current['revision'] == p['revision'] and current['duration'] == 2
