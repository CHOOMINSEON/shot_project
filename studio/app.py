import asyncio
import hashlib
import hmac
import json
import math
import os
import secrets
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from pydantic import BaseModel, Field, StrictInt

from . import db, timeline, worker, planning, proofreading, storage
from .settings import CHUNK_BYTES, DATA, MAX_FILE_BYTES, MAX_INPUT_SECONDS, MAX_OUTPUT_SECONDS, MODEL_DIR, MODEL_NAME, ROOT

LOCKS = {}
LOGIN_FAILURES = {}


def lock_for(asset_id):
    return LOCKS.setdefault(asset_id, asyncio.Lock())


def owner_password():
    supplied = os.getenv('STUDIO_PASSWORD')
    if supplied:
        if len(supplied) < 12:
            raise RuntimeError('STUDIO_PASSWORD는 12자 이상으로 설정해 주세요.')
        return supplied
    path = DATA / 'owner-password'
    if not path.exists():
        with path.open('x') as file:
            os.chmod(path, 0o600)
            file.write(secrets.token_urlsafe(24))
    return path.read_text().strip()


@asynccontextmanager
async def lifespan(app):
    # Reject duplicate workers instead of resetting another process's live jobs.
    with FileLock(DATA / 'worker.lock', timeout=0):
        db.init()
        owner_password()
        for temporary in (DATA / 'assets').glob('*/chunk-*.tmp'):
            temporary.unlink(missing_ok=True)
        thread = worker.start()
        try:
            yield
        finally:
            worker.STOP.set()
            await asyncio.to_thread(thread.join, 10)


app = FastAPI(title='신상집착 컷 스튜디오', lifespan=lifespan)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


@app.middleware('http')
async def security(request, call_next):
    # All media and project endpoints use the same owner session. No anonymous downloads.
    if request.method not in ['GET', 'HEAD', 'OPTIONS']:
        origin = request.headers.get('origin')
        if origin and origin.rstrip('/') != str(request.base_url).rstrip('/'):
            return JSONResponse({'detail': '다른 사이트에서 보낸 변경 요청은 허용되지 않습니다.'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail': '같은 사이트에서 다시 요청해 주세요.'}, status_code=403)
        limit = CHUNK_BYTES if '/chunks/' in request.url.path else 4 * 1024 * 1024
        try:
            if int(request.headers.get('content-length', '0')) > limit:
                return JSONResponse({'detail': '요청이 너무 큽니다. 청크 단위로 업로드해 주세요.'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail': '요청 크기 형식이 올바르지 않습니다.'}, status_code=400)
    if request.url.path.startswith('/api/') and request.url.path not in ['/api/login', '/api/health']:
        token = request.cookies.get('studio_owner', '')
        with db.connection() as conn:
            session = conn.execute('SELECT expires FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if not session or session['expires'] < time.time():
            return JSONResponse({'detail': '소유자 비밀번호로 로그인해 주세요.'}, status_code=401)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
def health():
    return {'status': 'ok', 'app': '신상집착 컷 스튜디오'}


class Login(BaseModel):
    password: str = Field(max_length=512)


@app.post('/api/login')
def login(body: Login, request: Request):
    address = request.client.host if request.client else 'local'
    failures = [t for t in LOGIN_FAILURES.get(address, []) if t > time.time() - 300]
    if len(failures) >= 10:
        raise HTTPException(429, '로그인 시도가 많습니다. 5분 후 다시 시도해 주세요.')
    if not hmac.compare_digest(body.password.encode(), owner_password().encode()):
        LOGIN_FAILURES[address] = failures + [time.time()]
        raise HTTPException(401, '소유자 비밀번호가 일치하지 않습니다.')
    LOGIN_FAILURES.pop(address, None)
    token = secrets.token_urlsafe(32)
    with db.connection() as conn:
        conn.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
        conn.execute('INSERT INTO sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + 86400 * 7))
    response = JSONResponse({'ok': True})
    response.set_cookie('studio_owner', token, httponly=True, secure=request.url.scheme == 'https', samesite='strict', max_age=86400 * 7)
    return response


@app.post('/api/logout')
def logout(request: Request):
    with db.connection() as conn:
        conn.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(request.cookies.get('studio_owner', '').encode()).hexdigest(),))
    response = JSONResponse({'ok': True})
    response.delete_cookie('studio_owner')
    return response


@app.get('/api/config')
def config(request: Request):
    usage = shutil.disk_usage(DATA)
    setup = getattr(request.app.state, 'desktop_setup', None)
    ready = setup.snapshot()['status'] == 'ready' if setup else (MODEL_DIR / 'model.bin').exists()
    return {'max_file_bytes': MAX_FILE_BYTES, 'max_input_seconds': MAX_INPUT_SECONDS,
            'max_output_seconds': MAX_OUTPUT_SECONDS, 'chunk_bytes': CHUNK_BYTES,
            'model_ready': ready, 'model_name': MODEL_NAME, 'free_bytes': usage.free, 'desktop': setup is not None,
            'privacy': '영상과 오디오는 이 앱의 서버에서 처리합니다. 외부 음성 인식 API에 전송하지 않습니다.'}


def project(ident):
    with db.connection() as conn:
        row = conn.execute('SELECT * FROM projects WHERE id=?', (ident,)).fetchone()
        assets = conn.execute('SELECT id FROM assets WHERE project_id=? ORDER BY created', (ident,)).fetchall()
    if not row:
        raise HTTPException(404, '프로젝트를 찾을 수 없습니다.')
    value = dict(row)
    value['state'] = json.loads(value['state'])
    for item in value['state'].get('captions', {}).get('items', []):
        item['reviewed'] = proofreading.approved(item)
    value['assets'] = [db.get_asset(a['id']) for a in assets]
    value['duration'] = timeline.duration(value['state'].get('clips', []))
    value['signature'] = timeline.signature(value['state'])
    value['render_signature'] = timeline.render_signature(value['state'])
    return value


class NewProject(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@app.get('/api/projects')
def projects():
    with db.connection() as conn:
        return [dict(r) for r in conn.execute('SELECT id,name,revision,updated FROM projects ORDER BY updated DESC')]


@app.post('/api/projects')
def create_project(body: NewProject):
    ident = db.uid()
    state = {'clips': [], 'protections': [], 'fps': 30, 'quality': 'standard', 'captions': {'items': []}, 'vocabulary': '', 'reference_script': ''}
    with db.connection() as conn:
        conn.execute('INSERT INTO projects VALUES (?,?,?,?,?,?)',
                     (ident, body.name, 1, json.dumps(state), time.time(), time.time()))
    return project(ident)


@app.get('/api/projects/{ident}')
def get_project(ident: str):
    return project(ident)


class Edit(BaseModel):
    revision: StrictInt
    state: dict
    name: str = Field(min_length=1, max_length=100)


def save(ident, revision, state, name):
    current = project(ident)
    timeline.validate_state(state, {a['id']: a for a in current['assets']})
    if state.get('planning'):
        planning.validate_plan(state['planning'])
    captions = state.get('captions', {})
    if captions.get('signature') == timeline.signature(state):
        timeline.validate_captions(captions.get('items', []), timeline.duration(state['clips']))
    serialized = json.dumps(state, ensure_ascii=False)
    if len(serialized.encode()) > 4 * 1024 * 1024:
        raise HTTPException(413, '편집 정보가 너무 큽니다.')
    with db.connection() as conn:
        result = conn.execute('UPDATE projects SET state=?,name=?,revision=revision+1,updated=? WHERE id=? AND revision=?',
                              (serialized, name, time.time(), ident, revision))
        if result.rowcount != 1:
            raise HTTPException(409, '다른 작업에서 프로젝트가 변경되었습니다. 최신 상태를 불러온 뒤 다시 편집해 주세요.')
    return project(ident)


@app.put('/api/projects/{ident}')
def edit_project(ident: str, body: Edit):
    return save(ident, body.revision, body.state, body.name)


class Upload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    size: StrictInt = Field(gt=0, le=MAX_FILE_BYTES)


@app.post('/api/projects/{ident}/uploads')
def new_upload(ident: str, body: Upload):
    project(ident)
    asset_id = db.uid()
    with db.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        pending = conn.execute("SELECT COALESCE(SUM(size),0) FROM assets WHERE status='uploading'").fetchone()[0]
        received = conn.execute("SELECT COALESCE(SUM(c.size),0) FROM chunks c JOIN assets a ON a.id=c.asset_id WHERE a.status='uploading'").fetchone()[0]
        if shutil.disk_usage(DATA).free < body.size + pending - received + 512 * 1024 * 1024:
            raise HTTPException(507, '원본을 보관할 저장 공간이 부족합니다. 진행 중인 업로드를 정리하거나 서버 저장 공간을 늘려 주세요.')
        (DATA / 'assets' / asset_id).mkdir()
        conn.execute('INSERT INTO assets (id,project_id,name,size,status,created) VALUES (?,?,?,?,?,?)',
                     (asset_id, ident, Path(body.name).name, body.size, 'uploading', time.time()))
    return {'id': asset_id, 'chunk_bytes': CHUNK_BYTES, 'chunk_count': math.ceil(body.size / CHUNK_BYTES)}


@app.get('/api/uploads/{ident}')
def upload_status(ident: str):
    asset = db.get_asset(ident)
    with db.connection() as conn:
        chunks = [dict(r) for r in conn.execute('SELECT idx,size,digest FROM chunks WHERE asset_id=? ORDER BY idx', (ident,))]
    return {'id': ident, 'name': asset['name'], 'size': asset['size'], 'status': asset['status'], 'chunks': chunks}


@app.put('/api/uploads/{ident}/chunks/{index}')
async def upload_chunk(ident: str, index: int, request: Request):
    asset = db.get_asset(ident)
    if asset['status'] != 'uploading' or not 0 <= index < math.ceil(asset['size'] / CHUNK_BYTES):
        raise HTTPException(409, '업로드 상태 또는 청크 번호가 올바르지 않습니다.')
    expected = min(CHUNK_BYTES, asset['size'] - index * CHUNK_BYTES)
    digest = hashlib.sha256()
    parent = DATA / 'assets' / ident
    temporary = parent / f'chunk-{db.uid()}.tmp'
    count = 0
    try:
        with temporary.open('xb') as file:
            async for part in request.stream():
                count += len(part)
                if count > expected:
                    raise HTTPException(413, '청크 크기가 선언한 파일 크기를 초과합니다.')
                if shutil.disk_usage(DATA).free < len(part) + 16 * 1024 * 1024:
                    raise HTTPException(507, '서버 저장 공간이 부족합니다.')
                file.write(part)
                digest.update(part)
        if count != expected:
            raise HTTPException(422, '청크가 불완전합니다. 해당 청크를 다시 전송해 주세요.')
        hashed = digest.hexdigest()
        async with lock_for(ident):
            if db.get_asset(ident)['status'] != 'uploading':
                raise HTTPException(409, '이미 완료·취소된 업로드입니다.')
            with db.connection() as conn:
                existing = conn.execute('SELECT digest FROM chunks WHERE asset_id=? AND idx=?', (ident, index)).fetchone()
                if existing:
                    if existing['digest'] != hashed:
                        raise HTTPException(409, '재전송한 파일 내용이 기존 청크와 다릅니다. 같은 원본으로 다시 시작해 주세요.')
                    return {'index': index, 'digest': hashed, 'duplicate': True}
            # A sparse staging file accepts out-of-order chunks without holding the source in RAM.
            staging = parent / 'upload.part'
            with staging.open('r+b' if staging.exists() else 'w+b') as output, temporary.open('rb') as source:
                storage.mark_sparse(output)
                output.seek(index * CHUNK_BYTES)
                shutil.copyfileobj(source, output, 1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
            with db.connection() as conn:
                conn.execute('INSERT INTO chunks VALUES (?,?,?,?)', (ident, index, count, hashed))
        return {'index': index, 'digest': hashed}
    finally:
        temporary.unlink(missing_ok=True)


@app.post('/api/uploads/{ident}/complete')
async def complete_upload(ident: str):
    async with lock_for(ident):
        asset = db.get_asset(ident)
        if asset['status'] != 'uploading':
            with db.connection() as conn:
                existing = conn.execute("SELECT id FROM jobs WHERE kind='ingest' AND json_extract(payload,'$.asset_id')=? ORDER BY created DESC LIMIT 1", (ident,)).fetchone()
            if existing:
                return {'job_id': existing['id']}
            raise HTTPException(409, '완료할 수 없는 업로드입니다.')
        with db.connection() as conn:
            chunks = conn.execute('SELECT idx,size FROM chunks WHERE asset_id=? ORDER BY idx', (ident,)).fetchall()
        if len(chunks) != math.ceil(asset['size'] / CHUNK_BYTES) or sum(c['size'] for c in chunks) != asset['size']:
            raise HTTPException(409, '누락된 청크가 있습니다. 이어올리기를 실행해 주세요.')
        original = worker.asset_path(ident)
        staging = original.parent / 'upload.part'
        # If a crash occurred after rename but before the DB update, recover the finalized file.
        path = staging if staging.exists() else original
        if not path.exists() or path.stat().st_size != asset['size']:
            raise HTTPException(409, '원본 파일 크기가 일치하지 않습니다. 업로드를 다시 시작해 주세요.')
        if staging.exists():
            staging.replace(original)
        job_id = db.uid()
        with db.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE assets SET status='checking' WHERE id=?", (ident,))
            conn.execute('INSERT INTO jobs (id,project_id,kind,status,payload,created,updated) VALUES (?,?,?,?,?,?,?)',
                         (job_id, asset['project_id'], 'ingest', 'queued', json.dumps({'asset_id': ident}), time.time(), time.time()))
        return {'job_id': job_id}


@app.delete('/api/uploads/{ident}')
async def discard_upload(ident: str):
    async with lock_for(ident):
        asset = db.get_asset(ident)
        if asset['status'] not in ['uploading', 'invalid']:
            raise HTTPException(409, '처리 중이거나 보관된 원본은 업로드 취소로 삭제할 수 없습니다.')
        with db.connection() as conn:
            conn.execute('DELETE FROM chunks WHERE asset_id=?', (ident,))
            conn.execute('DELETE FROM assets WHERE id=?', (ident,))
        shutil.rmtree(DATA / 'assets' / ident, ignore_errors=True)
    return {'ok': True}


@app.get('/api/assets/{ident}/video')
def video(ident: str):
    asset = db.get_asset(ident)
    if asset['status'] != 'ready':
        raise HTTPException(409, '영상 검사가 완료되지 않았습니다.')
    return FileResponse(worker.asset_path(ident), media_type='video/mp4' if asset['metadata']['codec'] in ['h264', 'hevc'] else 'video/webm')


@app.get('/api/assets/{ident}/thumbnail')
def thumbnail(ident: str):
    db.get_asset(ident)
    path = DATA / 'assets' / ident / 'thumbnail.jpg'
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type='image/jpeg')


class Analysis(BaseModel):
    asset_id: str
    transcribe: bool = True
    vocabulary: str = Field(default='', max_length=1000)
    names: list[str] = Field(default_factory=list, max_length=100)


@app.post('/api/projects/{ident}/analyze')
def analyze(ident: str, body: Analysis, request: Request):
    current = project(ident)
    if not any(a['id'] == body.asset_id and a['status'] == 'ready' for a in current['assets']):
        raise HTTPException(422, '이 프로젝트의 검사 완료 원본을 선택해 주세요.')
    setup = getattr(request.app.state, 'desktop_setup', None)
    if body.transcribe and setup and setup.snapshot()['status'] != 'ready':
        raise HTTPException(503, '자막 모델을 준비하고 있습니다. 상단의 준비 상태를 확인해 주세요.')
    if body.transcribe and not (MODEL_DIR / 'model.bin').exists():
        raise HTTPException(503, '음성 인식 모델이 준비되지 않았습니다. 공백만 분석하거나 서버에서 모델을 설치해 주세요.')
    return {'job_id': db.job(ident, 'analyze', {**body.model_dump(), 'model': MODEL_NAME})}


class Cuts(BaseModel):
    revision: StrictInt
    asset_id: str
    candidates: list[dict] = Field(max_length=10000)
    restore: bool = False


class AutoCut(BaseModel):
    revision: StrictInt
    asset_id: str
    threshold_db: float = Field(default=-40, ge=-70, le=-15, allow_inf_nan=False)
    minimum: float = Field(default=.6, ge=.1, le=10, allow_inf_nan=False)
    before: float = Field(default=.12, ge=0, le=2, allow_inf_nan=False)
    after: float = Field(default=.2, ge=0, le=2, allow_inf_nan=False)


@app.post('/api/projects/{ident}/auto-cut')
def auto_cut(ident: str, body: AutoCut):
    current = project(ident)
    if body.revision != current['revision']:
        raise HTTPException(409, '편집이 변경되었어요. 최신 편집을 불러온 뒤 다시 실행해 주세요.')
    asset = next((a for a in current['assets'] if a['id'] == body.asset_id and a['status'] == 'ready'), None)
    if not asset or not any(c['asset_id'] == body.asset_id for c in current['state']['clips']):
        raise HTTPException(422, '타임라인에 있는 검사 완료 원본을 선택해 주세요.')
    if not asset['metadata']['has_audio']:
        raise HTTPException(422, '오디오가 없는 영상은 무음을 판단할 수 없어요. 수동 편집을 사용해 주세요.')
    # Serialized with the worker's final commit; reject duplicate clicks across tabs.
    with db.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        revision = conn.execute('SELECT revision FROM projects WHERE id=?', (ident,)).fetchone()['revision']
        if revision != body.revision:
            raise HTTPException(409, '편집이 변경되었어요. 최신 편집을 불러온 뒤 다시 실행해 주세요.')
        if conn.execute("SELECT 1 FROM jobs WHERE project_id=? AND kind='auto_cut' AND status IN ('queued','running')", (ident,)).fetchone():
            raise HTTPException(409, '무음 자동 편집이 진행 중이에요. 결과를 기다려 주세요.')
        job_id = db.uid()
        conn.execute('INSERT INTO jobs (id,project_id,kind,status,payload,created,updated) VALUES (?,?,?,?,?,?,?)',
                     (job_id, ident, 'auto_cut', 'queued', json.dumps(body.model_dump()), time.time(), time.time()))
    return {'job_id': job_id}


class UndoAutoCut(BaseModel):
    revision: StrictInt


@app.post('/api/projects/{ident}/auto-cut/{job_id}/undo')
def undo_auto_cut(ident: str, job_id: str, body: UndoAutoCut):
    current = project(ident)
    with db.connection() as conn:
        row = conn.execute("SELECT payload,result FROM jobs WHERE id=? AND project_id=? AND kind='auto_cut'", (job_id, ident)).fetchone()
    if not row:
        raise HTTPException(404, '자동 편집 작업을 찾지 못했어요.')
    payload, result = json.loads(row['payload']), json.loads(row['result'])
    if not result.get('applied') or current['revision'] != result['revision']:
        raise HTTPException(409, '자동 편집 이후 변경한 내용이 있어요. 타임라인의 취소 또는 구간 복원을 사용해 주세요.')
    return save(ident, body.revision, payload['before_state'], current['name'])


@app.post('/api/projects/{ident}/cuts')
def cuts(ident: str, body: Cuts):
    current = project(ident)
    asset = next((a for a in current['assets'] if a['id'] == body.asset_id), None)
    if not asset or asset['status'] != 'ready':
        raise HTTPException(422, '원본을 확인해 주세요.')
    for candidate in body.candidates:
        a, b = candidate.get('start'), candidate.get('end')
        if not timeline.finite(a) or not timeline.finite(b) or not 0 <= a < b <= asset['metadata']['duration']:
            raise HTTPException(422, '공백 후보 시간이 원본 범위를 벗어났습니다.')
    state = (timeline.restore_cuts if body.restore else timeline.apply_cuts)(current['state'], body.asset_id, body.candidates)
    return save(ident, body.revision, state, current['name'])


class Captions(BaseModel):
    revision: StrictInt
    target: int = Field(default=14, ge=10, le=30)


@app.post('/api/projects/{ident}/captions')
def captions(ident: str, body: Captions):
    current = project(ident)
    state = current['state']
    assets = {a['id']: a for a in current['assets']}
    timeline.validate_state(state, assets)
    state['captions'] = timeline.generate_captions(state, assets, body.target)
    return save(ident, body.revision, state, current['name'])


class Review(BaseModel):
    revision: StrictInt
    caption_ids: list[str] = Field(min_length=1, max_length=3000)


@app.post('/api/projects/{ident}/captions/review')
def review_captions(ident: str, body: Review):
    current = project(ident)
    caps = current['state'].get('captions', {})
    if caps.get('signature') != current['signature']:
        raise HTTPException(409, '자막을 먼저 동기화해 주세요.')
    timeline.validate_captions(caps.get('items', []), current['duration'])
    items = {c['id']: c for c in caps.get('items', [])}
    if not set(body.caption_ids) <= items.keys():
        raise HTTPException(422, '검수할 자막을 찾을 수 없습니다.')
    for ident in body.caption_ids:
        item = items[ident]
        if any('빈칸' in reason for reason in proofreading.inspect_text(item['text'])['reasons']):
            raise HTTPException(422, '미정 빈칸을 실제 내용으로 채운 뒤 검수해 주세요.')
        item['review_token'] = proofreading.caption_token(item)
    return save(current['id'], body.revision, current['state'], current['name'])


class TextReview(BaseModel):
    text: str = Field(max_length=30000)
    corrections: str = Field(default='', max_length=10000)


@app.post('/api/proofread')
def proofread(body: TextReview):
    return proofreading.inspect_text(body.text, body.corrections)


class PlanningRequest(BaseModel):
    revision: StrictInt
    brief: planning.Brief


@app.post('/api/projects/{ident}/planning')
def create_plan(ident: str, body: PlanningRequest):
    current = project(ident)
    state = current['state']
    state['planning'] = planning.build(body.brief)
    return save(ident, body.revision, state, current['name'])


@app.get('/api/projects/{ident}/planning/review')
def review_plan(ident: str):
    state = project(ident)['state']
    if not state.get('planning'):
        raise HTTPException(404, '먼저 기획 초안을 만들어 주세요.')
    return planning.audit(state['planning'], state.get('corrections', ''))


@app.get('/api/projects/{ident}/planning.md')
def download_plan(ident: str):
    plan = project(ident)['state'].get('planning')
    if not plan:
        raise HTTPException(404, '먼저 기획 초안을 만들어 주세요.')
    return Response(planning.markdown(plan), media_type='text/markdown; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="food-short-plan.md"'})


class ApplyPlan(BaseModel):
    revision: StrictInt


@app.post('/api/projects/{ident}/planning/apply')
def apply_plan(ident: str, body: ApplyPlan):
    current = project(ident)
    plan = current['state'].get('planning')
    if not plan:
        raise HTTPException(404, '먼저 기획 초안을 만들어 주세요.')
    state = planning.apply_storyboard(current['state'], plan, {a['id']: a for a in current['assets']})
    return save(ident, body.revision, state, current['name'])


@app.get('/api/projects/{ident}/captions.srt')
def download_srt(ident: str):
    current = project(ident)
    captions = current['state'].get('captions', {})
    if captions.get('signature') != current['signature']:
        raise HTTPException(409, '자막 동기화가 필요합니다. 최신 편집본 기준으로 다시 생성해 주세요.')
    proofreading.require_review(captions.get('items', []))
    return Response(timeline.srt(captions.get('items', []), current['duration']), media_type='application/x-subrip; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="iyoring_review_roughcut.srt"'})


class Render(BaseModel):
    revision: StrictInt
    mode: str = 'full'
    preview: bool = False
    filename: str = Field(default='iyoring_review_roughcut', min_length=1, max_length=100)


@app.post('/api/projects/{ident}/render')
def render(ident: str, body: Render):
    current = project(ident)
    if body.revision != current['revision']:
        raise HTTPException(409, '최신 편집 버전으로 다시 요청해 주세요.')
    groups = timeline.export_groups(current['state'], body.mode)
    captions = current['state'].get('captions', {})
    if captions.get('items') and captions.get('signature') != current['signature']:
        raise HTTPException(409, '자막 동기화가 필요합니다. 컷이 변경된 후 자막을 다시 생성해 주세요.')
    timeline.validate_captions(captions.get('items', []), current['duration'])
    if not body.preview:
        proofreading.require_review(captions.get('items', []))
    import re
    filename = re.sub(r'[^\w가-힣.-]', '_', body.filename).strip('.') or 'iyoring_review'
    # Conservative bounded-bitrate estimate: pieces + final + ZIP, with a safety margin.
    estimate = current['duration'] * (4_000_000 if not body.preview else 500_000) * (3 if not body.preview else 2) + 512 * 1024 * 1024
    if shutil.disk_usage(DATA).free < estimate:
        raise HTTPException(507, '렌더·최종 영상·ZIP을 저장할 공간이 부족합니다. 서버 공간을 늘리거나 더 작은 구간으로 출력해 주세요.')
    return {'job_id': db.job(ident, 'render', {**body.model_dump(), 'filename': filename, 'state': current['state']})}


@app.get('/api/jobs')
def jobs(project_id: str | None = None):
    with db.connection() as conn:
        rows = conn.execute('SELECT id,project_id,kind,status,progress,message,result,created,updated FROM jobs '
                            + ('WHERE project_id=? ' if project_id else '') + 'ORDER BY created DESC LIMIT 100',
                            (project_id,) if project_id else ()).fetchall()
    return [{**dict(r), 'result': json.loads(r['result'])} for r in rows]


@app.post('/api/jobs/{ident}/cancel')
def cancel(ident: str):
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET cancel=1 WHERE id=? AND status IN ('queued','running')", (ident,))
    return {'ok': True}


@app.post('/api/jobs/{ident}/retry')
def retry(ident: str):
    with db.connection() as conn:
        row = conn.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row or row['status'] not in ['failed', 'cancelled']:
            raise HTTPException(409, '실패·취소된 작업만 다시 실행할 수 있습니다.')
        if row['kind'] == 'ingest':
            conn.execute("UPDATE assets SET status='checking' WHERE id=?", (json.loads(row['payload'])['asset_id'],))
        conn.execute("UPDATE jobs SET status='queued',cancel=0,message='다시 실행 대기',updated=? WHERE id=?", (time.time(), ident))
    return {'job_id': ident}


@app.get('/api/exports/{ident}/{filename}')
def output_file(ident: str, filename: str, inline: bool = False):
    with db.connection() as conn:
        row = conn.execute('SELECT status,result FROM jobs WHERE id=?', (ident,)).fetchone()
    if not row or row['status'] != 'completed' or filename not in [f['name'] for f in json.loads(row['result']).get('files', [])]:
        raise HTTPException(404, '완료된 출력 파일을 찾을 수 없습니다.')
    path = DATA / 'exports' / ident / filename
    if not path.is_file():
        raise HTTPException(404, '출력 파일이 없습니다.')
    return FileResponse(path, filename=None if inline else filename, media_type='video/mp4' if filename.endswith('.mp4') else None)


@app.delete('/api/exports/{ident}')
def delete_output(ident: str):
    with db.connection() as conn:
        row = conn.execute('SELECT status FROM jobs WHERE id=?', (ident,)).fetchone()
        if not row or row['status'] not in ['completed', 'failed', 'cancelled']:
            raise HTTPException(409, '처리 중인 출력은 먼저 취소해 주세요.')
        conn.execute("UPDATE jobs SET result='{}',message='출력 파일 정리 완료' WHERE id=?", (ident,))
    shutil.rmtree(DATA / 'exports' / ident, ignore_errors=True)
    shutil.rmtree(DATA / 'work' / ident, ignore_errors=True)
    return {'ok': True}


app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
