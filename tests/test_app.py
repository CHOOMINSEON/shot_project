import hashlib
import io
import json
import subprocess
import time
import zipfile
import pytest

from studio import timeline
from studio.media import probe
from studio.settings import CHUNK_BYTES, DATA


def wait_job(client, ident, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = next(j for j in client.get('/api/jobs').json() if j['id'] == ident)
        if value['status'] in ['completed', 'failed', 'cancelled']:
            return value
        time.sleep(.1)
    raise AssertionError('Job did not finish')


def upload_video(client, sample):
    p = client.post('/api/projects', json={'name': '이요링 테스트'}).json()
    content = sample.read_bytes()
    session = client.post(f'/api/projects/{p["id"]}/uploads', json={'name': sample.name, 'size': len(content)}).json()
    assert client.put(f'/api/uploads/{session["id"]}/chunks/0', content=content).status_code == 200
    completed = client.post(f'/api/uploads/{session["id"]}/complete').json()
    assert wait_job(client, completed['job_id'])['status'] == 'completed'
    return client.get('/api/projects/' + p['id']).json(), session['id']


def test_auth_and_csrf(client):
    client.cookies.clear()
    assert client.get('/api/health').status_code == 200
    assert client.get('/api/projects').status_code == 401
    assert client.post('/api/login', json={'password': 'wrong'}).status_code == 401
    response = client.post('/api/login', json={'password': 'fixture-owner-password-only'})
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.post('/api/projects', json={'name': 'x'}, headers={'origin': 'https://foreign.example'}).status_code == 403


def test_upload_size_boundaries(owner, monkeypatch):
    from collections import namedtuple
    from studio import app as app_module
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(app_module.shutil, 'disk_usage', lambda _: usage(100_000_000_000, 0, 100_000_000_000))
    p = owner.post('/api/projects', json={'name': '용량 검증'}).json()
    endpoint = f'/api/projects/{p["id"]}/uploads'
    for invalid in [0, 10_000_000_001, 3.5]:
        assert owner.post(endpoint, json={'name': 'x.mp4', 'size': invalid}).status_code == 422
    response = owner.post(endpoint, json={'name': 'max.mp4', 'size': 10_000_000_000})
    assert response.status_code == 200
    assert response.json()['chunk_count'] == 1193
    owner.delete('/api/uploads/' + response.json()['id'])


def test_out_of_order_resume_and_conflicting_chunk(owner):
    p = owner.post('/api/projects', json={'name': '이어올리기'}).json()
    ident = owner.post(f'/api/projects/{p["id"]}/uploads', json={'name': 'chunks.mp4', 'size': CHUNK_BYTES + 3}).json()['id']
    url = f'/api/uploads/{ident}'
    assert owner.put(url + '/chunks/1', content=b'end').status_code == 200
    assert owner.post(url + '/complete').status_code == 409
    assert owner.put(url + '/chunks/1', content=b'end').json()['duplicate']
    assert owner.put(url + '/chunks/1', content=b'bad').status_code == 409
    assert owner.put(url + '/chunks/0', content=b'a' * CHUNK_BYTES).status_code == 200
    assert owner.put(url + '/chunks/2', content=b'x').status_code == 409
    assert owner.get(url).json()['chunks'][0]['digest'] == hashlib.sha256(b'a' * CHUNK_BYTES).hexdigest()
    path = DATA / 'assets' / ident / 'upload.part'
    assert path.stat().st_size == CHUNK_BYTES + 3
    with path.open('rb') as file:
        file.seek(CHUNK_BYTES)
        assert file.read() == b'end'
    assert owner.delete(url).status_code == 200
    assert not path.parent.exists()


def test_ten_gb_sparse_offsets_are_not_a_dense_load_test(owner, monkeypatch):
    from collections import namedtuple
    from studio import app as app_module
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(app_module.shutil, 'disk_usage', lambda _: usage(100_000_000_000, 0, 100_000_000_000))
    p = owner.post('/api/projects', json={'name': '10GB 희소 주소 검증'}).json()
    limit = 10_000_000_000
    session = owner.post(f'/api/projects/{p["id"]}/uploads', json={'name': 'sparse.mp4', 'size': limit}).json()
    last = session['chunk_count'] - 1
    final_size = limit - last * CHUNK_BYTES
    endpoint = '/api/uploads/' + session['id']
    response = owner.put(endpoint + f'/chunks/{last}', content=b'z' * final_size)
    assert response.status_code == 200
    path = DATA / 'assets' / session['id'] / 'upload.part'
    assert path.stat().st_size == limit
    with path.open('rb') as file:
        file.seek(limit - 1)
        assert file.read(1) == b'z'
    from studio.storage import allocated_bytes
    assert allocated_bytes(path) < 2 * CHUNK_BYTES
    assert owner.post(endpoint + '/complete').status_code == 409
    assert owner.delete(endpoint).status_code == 200


def test_hdr_tone_mapping_pipeline_executes(tmp_path):
    from studio.media import render_piece
    for transfer in ['smpte2084', 'arib-std-b67']:
        source = tmp_path / f'{transfer}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=0.5',
                        '-vf', f'format=yuv420p10le,zscale=pin=bt709:tin=bt709:min=bt709:p=bt2020:t={transfer}:m=bt2020nc',
                        '-c:v', 'libx265', '-threads', '2', '-x265-params', 'log-level=error:pools=1:frame-threads=1',
                        '-color_primaries', 'bt2020', '-color_trc', transfer, '-colorspace', 'bt2020nc', str(source)], check=True)
        info = probe(source)
        assert info['hdr']
        target = tmp_path / f'{transfer}-sdr.mp4'
        render_piece(source, {'start': 0, 'end': .5, 'frame': {'mode': 'fit'}}, info, target,
                     tmp_path / 'work', 30, 'standard', True, lambda: False, lambda value: None)
        output = probe(target)
        assert output['transfer'] == 'bt709'
        assert not output['hdr']


@pytest.mark.parametrize('fps', [30, 60])
def test_real_render_subtitles_zip_range_and_version(owner, sample, fps):
    p, asset_id = upload_video(owner, sample)
    assert p['assets'][0]['metadata']['duration'] == 8
    state = p['state']
    state['fps'] = fps
    first = state['clips'][0]
    first.update(start=0, end=1.4, label='첫 제품', frame={'mode': 'blur'})
    state['clips'].append({**first, 'id': 'second', 'start': 5, 'end': 6.8, 'label': '둘째 제품', 'frame': {'mode': 'fill', 'x': .3, 'y': .8, 'zoom': 1.1}})
    state['captions'] = {'signature': timeline.signature(state), 'items': [
        {'id': 'c1', 'start': .1, 'end': 1.2, 'text': '안 달아요 · 1,500원'},
        {'id': 'c2', 'start': 1.5, 'end': 3, 'text': '10점 만점에 8점'}]}
    endpoint = '/api/projects/' + p['id']
    edited = owner.put(endpoint, json={'name': p['name'], 'revision': p['revision'], 'state': state}).json()
    conflict = owner.put(endpoint, json={'name': p['name'], 'revision': p['revision'], 'state': state})
    assert conflict.status_code == 409
    assert owner.get(endpoint + '/captions.srt').status_code == 422
    edited = owner.post(endpoint + '/captions/review', json={'revision': edited['revision'], 'caption_ids': ['c1', 'c2']}).json()
    srt_response = owner.get(endpoint + '/captions.srt')
    assert '안 달아요' in srt_response.text
    result = owner.post(endpoint + '/render', json={'revision': edited['revision'], 'mode': 'products', 'filename': '한글_리뷰'})
    assert result.status_code == 200, result.text
    job = wait_job(owner, result.json()['job_id'])
    assert job['status'] == 'completed', job['message']
    files = job['result']['files']
    for entry in files:
        response = owner.get(f'/api/exports/{job["id"]}/{entry["name"]}')
        assert response.status_code == 200
        assert len(response.content) == entry['size']
        if entry['name'].endswith('.mp4'):
            response = owner.get(f'/api/exports/{job["id"]}/{entry["name"]}', headers={'Range': 'bytes=0-63'})
            assert response.status_code == 206
            assert len(response.content) == 64
            path = DATA / 'exports' / job['id'] / entry['name']
            info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)]))
            video = next(s for s in info['streams'] if s['codec_type'] == 'video')
            audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
            assert (video['width'], video['height'], video['codec_name'], video['avg_frame_rate']) == (1080, 1920, 'h264', f'{fps}/1')
            assert (audio['codec_name'], audio['sample_rate'], audio['channels']) == ('aac', '48000', 2)
    archive = next(f for f in files if f['name'].endswith('.zip'))
    with zipfile.ZipFile(io.BytesIO(owner.get(f'/api/exports/{job["id"]}/{archive["name"]}').content)) as zipped:
        assert zipped.testzip() is None
        assert 'edit-list.json' in zipped.namelist()
        local = zipped.read('002_한글_리뷰.srt').decode()
        assert '00:00:00,100' in local
        assert '10점 만점에 8점' in local
        assert json.loads(zipped.read('edit-list.json'))['revision'] == edited['revision']
    state['clips'].reverse()
    newer = owner.put(endpoint, json={'name': p['name'], 'revision': edited['revision'], 'state': state}).json()
    assert owner.get(endpoint + '/captions.srt').status_code == 409
    assert owner.post(endpoint + '/render', json={'revision': newer['revision']}).status_code == 409
    # Previously exported files remain frozen to their actual revision.
    assert owner.get(f'/api/exports/{job["id"]}/{archive["name"]}').status_code == 200


def test_real_silero_vad_and_no_transcript_invention(owner, sample):
    p, ident = upload_video(owner, sample)
    response = owner.post('/api/projects/' + p['id'] + '/analyze', json={'asset_id': ident, 'transcribe': False})
    job = wait_job(owner, response.json()['job_id'])
    assert job['status'] == 'completed', job['message']
    p = owner.get('/api/projects/' + p['id']).json()
    analysis = p['assets'][0]['analysis']
    assert len(analysis['peaks']) == 32
    assert analysis['candidates']
    assert analysis['words'] == []
    assert not analysis['transcribed']


def test_cancel_queued_job(owner, sample):
    p, ident = upload_video(owner, sample)
    # Set cancellation in the same DB transaction as insertion to avoid a scheduling race.
    from studio import db
    job_id = db.job(p['id'], 'analyze', {'asset_id': ident, 'transcribe': False})
    assert owner.post('/api/jobs/' + job_id + '/cancel').status_code == 200
    job = wait_job(owner, job_id)
    assert job['status'] == 'cancelled'
    assert (DATA / 'assets' / ident / 'original').exists()


def test_asr_numeric_values_and_vad_rerun_preserve_words(owner, sample, monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    from studio import worker
    from studio.settings import MODEL_DIR
    class FixtureModel:
        def transcribe(self, *args, **kwargs):
            words = [SimpleNamespace(start=np.float32(1), end=np.float32(2), word='안 달아요', probability=np.float32(.8))]
            return iter([SimpleNamespace(words=words)]), None
    monkeypatch.setattr(worker, 'load_model', lambda: FixtureModel())
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / 'model.bin').touch()
    p, ident = upload_video(owner, sample)
    endpoint = '/api/projects/' + p['id']
    result = owner.post(endpoint + '/analyze', json={'asset_id': ident, 'transcribe': True})
    j = wait_job(owner, result.json()['job_id'])
    assert j['status'] == 'completed', j['message']
    result = owner.post(endpoint + '/analyze', json={'asset_id': ident, 'transcribe': False})
    assert wait_job(owner, result.json()['job_id'])['status'] == 'completed'
    data = owner.get(endpoint).json()['assets'][0]['analysis']
    assert data['words'][0]['text'] == '안 달아요'
    assert data['words'][0]['review'] is True
    assert data['words'][0]['confidence'] == .8
    assert data['transcribed']


def test_two_hour_duration_metadata_limit(tmp_path):
    import pytest
    for seconds in [7200, 7201]:
        path = tmp_path / f'{seconds}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=size=16x16:rate=1:duration={seconds}',
                        '-c:v', 'libx264', '-threads', '2', str(path)], check=True)
        if seconds == 7200:
            assert probe(path)['duration'] == 7200
        else:
            with pytest.raises(ValueError, match='2시간'):
                probe(path)
