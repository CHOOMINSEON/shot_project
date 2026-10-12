import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
import wave
import zipfile
from pathlib import Path

import numpy as np

from . import db, timeline, proofreading, script_edit
from .media import Cancelled, probe, render_piece, run_ffmpeg
from .settings import DATA, MODEL_DIR, MODEL_NAME, WINDOW_SECONDS, MAX_OUTPUT_SECONDS

STOP = threading.Event()
MODEL = None
MODEL_ID = None
MODEL_LOCK = threading.Lock()


def asset_path(ident):
    return DATA / 'assets' / ident / 'original'


def atomic_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def is_cancelled(ident):
    with db.connection() as conn:
        row = conn.execute('SELECT cancel FROM jobs WHERE id=?', (ident,)).fetchone()
    return STOP.is_set() or not row or bool(row['cancel'])


def check_cancel(ident):
    if is_cancelled(ident):
        raise Cancelled()


def update(ident, value, message):
    db.update_job(ident, progress=max(0, min(1, value)), message=message)


def load_model(name=None):
    global MODEL, MODEL_ID
    name = name or MODEL_NAME
    if name not in ['tiny', 'base', 'small', 'medium']:
        raise ValueError('지원하지 않는 음성 인식 모델입니다.')
    directory = DATA / 'models' / f'whisper-{name}'
    if name == 'base' and not (directory / 'model.bin').exists():
        directory = DATA / 'models' / 'whisper'
    with MODEL_LOCK:
        if MODEL is None or MODEL_ID != name:
            if not (directory / 'model.bin').exists():
                raise ValueError('음성 인식 모델이 준비되지 않았습니다. 서버에서 scripts/download_model.py를 실행해 주세요. 공백 분석과 수동 편집은 모델 없이 사용할 수 있습니다.')
            from faster_whisper import WhisperModel
            MODEL = None
            MODEL = WhisperModel(str(directory), device='cpu', compute_type='int8', cpu_threads=2, num_workers=1)
            MODEL_ID = name
        return MODEL


def ingest(ident, payload):
    asset = db.get_asset(payload['asset_id'])
    path = asset_path(asset['id'])
    metadata = probe(path, allow_audio=True)
    check_cancel(ident)
    update(ident, .4, '영상 정보 확인 완료 · 대표 이미지 생성')
    if metadata['has_video']:
        run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-ss', str(min(1, metadata['duration'] / 2)),
                '-i', path, '-frames:v', '1', '-vf', 'scale=240:-2', '-update', '1', path.parent / 'thumbnail.jpg'],
               DATA / 'work' / ident, lambda: is_cancelled(ident))
    with db.connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE assets SET status=?,metadata=? WHERE id=?', ('ready', json.dumps(metadata), asset['id']))
        row = conn.execute('SELECT state,revision FROM projects WHERE id=?', (asset['project_id'],)).fetchone()
        state = json.loads(row['state'])
        # Ingest completion is a versioned edit, never an overwrite of newer user state.
        if metadata['has_video']:
            state['clips'].append({'id': db.uid(), 'asset_id': asset['id'], 'start': 0,
                               'end': math.floor(metadata['duration'] * state.get('fps', 30)) / state.get('fps', 30), 'label': Path(asset['name']).stem,
                               'frame': {'mode': 'fit', 'x': .5, 'y': .5, 'zoom': 1}})
        conn.execute('UPDATE projects SET state=?,revision=revision+1,updated=? WHERE id=?',
                     (json.dumps(state, ensure_ascii=False), time.time(), asset['project_id']))
    return {'asset_id': asset['id'], 'metadata': metadata}


def analyze(ident, payload):
    asset = db.get_asset(payload['asset_id'])
    if asset['status'] != 'ready':
        raise ValueError('원본 영상 검사가 먼저 완료되어야 합니다.')
    if not asset['metadata']['has_audio']:
        raise ValueError('오디오가 없는 영상입니다. 수동 편집을 사용해 주세요.')
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    work = DATA / 'work' / ident
    if payload.get('script_asset_checkpoint'):
        work = work / payload['asset_id']
    work.mkdir(parents=True, exist_ok=True)
    checkpoint = work / 'analysis.json'
    length = asset['metadata']['duration']
    data = json.loads(checkpoint.read_text(encoding='utf-8')) if checkpoint.exists() else {'speech': [], 'words': [], 'peaks': [], 'next': 0}
    # Freeze model identity across resumed windows, including checkpoints from the original base version.
    model_name = data.get('model') or ('base' if data['next'] and data['words'] else payload.get('model', MODEL_NAME))
    model = (load_model() if model_name == MODEL_NAME else load_model(model_name)) if payload.get('transcribe') else None
    if model:
        data['model'] = model_name
    for start in range(int(data['next']), int(np.ceil(length)), WINDOW_SECONDS):
        check_cancel(ident)
        end = min(start + WINDOW_SECONDS, length)
        # One-second context overlaps; retain words by their midpoint to avoid duplicates.
        left, right = max(0, start - 1), min(length, end + 1)
        wav = work / 'audio.wav'
        update(ident, start / length, f'{int(start)} / {int(length)}초 · 오디오 구간 추출')
        run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-ss', str(left), '-i', asset_path(asset['id']),
                    '-t', str(right - left), '-vn', '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', wav],
                   work, lambda: is_cancelled(ident))
        with wave.open(str(wav), 'rb') as audio_file:
            audio = np.frombuffer(audio_file.readframes(audio_file.getnframes()), dtype='<i2').astype(np.float32) / 32768.
        speech = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=100, speech_pad_ms=0), sampling_rate=16000)
        data['speech'] += [[max(start, left + s['start'] / 16000), min(end, left + s['end'] / 16000)]
                           for s in speech if left + s['start'] / 16000 < end and left + s['end'] / 16000 > start]
        for sec in np.arange(start, end, .25):
            chunk = audio[int((sec - left) * 16000):int(min(right, sec + .25) * 16000 - left * 16000)]
            data['peaks'].append(round(float(np.max(np.abs(chunk))) if len(chunk) else 0., 3))
        if model:
            segments, _ = model.transcribe(audio, language='ko', word_timestamps=True, beam_size=5,
                                          vad_filter=True, initial_prompt=payload.get('vocabulary', '')[:1000],
                                          hotwords=payload.get('vocabulary', '')[:1000],
                                          condition_on_previous_text=False, hallucination_silence_threshold=1.)
            for segment in segments:
                check_cancel(ident)
                for word in segment.words or []:
                    a, b = float(left + word.start), float(left + word.end)
                    if start <= (a + b) / 2 < end and b > a:
                        data['words'].append({'id': f'w{len(data["words"])}', 'start': a, 'end': min(length, b),
                                              'text': word.word, 'confidence': round(float(word.probability), 4),
                                              'review': bool(word.probability < .85)})
        data['next'] = start + WINDOW_SECONDS
        atomic_json(checkpoint, data)
        wav.unlink(missing_ok=True)
        del audio
    data['speech'] = timeline.merge_intervals(data['speech'])
    data['candidates'] = timeline.cut_candidates(data['speech'], length)
    data['products'] = timeline.product_candidates(data['words'], payload.get('names', []), length) if model else []
    data['transcribed'] = bool(model)
    # A VAD-only re-run must not erase a previously completed transcript.
    if not model:
        for key in ['words', 'products', 'transcribed', 'model']:
            if key in asset['analysis']:
                data[key] = asset['analysis'][key]
    with db.connection() as conn:
        if asset['analysis'].get('silence'):
            data['silence'] = asset['analysis']['silence']
        conn.execute('UPDATE assets SET analysis=? WHERE id=?', (json.dumps(data, ensure_ascii=False), asset['id']))
    return {'asset_id': asset['id'], 'candidates': len(data['candidates']), 'words': len(data['words'])}


def render(ident, payload):
    state = payload['state']  # Frozen revision; subsequent edits cannot mutate this export.
    preview = payload.get('preview', False)
    groups = timeline.export_groups(state, payload.get('mode', 'full'))
    captions = state.get('captions', {})
    if captions.get('items') and captions.get('signature') != timeline.signature(state):
        raise ValueError('컷이 변경되어 자막 동기화가 필요합니다. 자막을 다시 생성·검토해 주세요.')
    items = captions.get('items', [])
    timeline.validate_captions(items, timeline.duration(state['clips']))
    if not preview:
        if state.get('script_edit') and not state['script_edit'].get('complete'):
            raise ValueError('대본의 빈칸·못 찾은 대사를 먼저 확인해 주세요.')
        proofreading.require_review(items)
    work, target = DATA / 'work' / ident, DATA / 'exports' / ident
    work.mkdir(exist_ok=True)
    target.mkdir(exist_ok=True)
    total = timeline.duration(state['clips'])
    estimate = total * (4_000_000 if not preview else 500_000) * (3 if not preview else 2) + 512 * 1024 * 1024
    if shutil.disk_usage(DATA).free < estimate:
        raise ValueError('대기 중 서버 저장 공간이 줄었습니다. 출력 파일을 정리하거나 저장 공간을 늘린 뒤 재시도해 주세요.')
    elapsed = 0.
    file_list, edit_list = [], []
    base = payload['filename']
    for gi, (label, clips) in enumerate(groups, 1):
        pieces = []
        group_start = elapsed
        for clip in clips:
            check_cancel(ident)
            asset = db.get_asset(clip['asset_id'])
            visual = db.get_asset(clip['visual_asset_id']) if clip.get('visual_asset_id') else None
            key = hashlib.sha256(json.dumps([clip, state.get('fps', 30), state.get('quality', 'standard'), preview], sort_keys=True).encode()).hexdigest()
            piece = work / f'{key}.mp4'
            clip_length = clip['end'] - clip['start']
            if not piece.exists():
                partial = work / f'{key}.partial.mp4'
                partial.unlink(missing_ok=True)
                render_piece(asset_path(asset['id']), clip, asset['metadata'], partial, work,
                             state.get('fps', 30), state.get('quality', 'standard'), preview,
                             lambda: is_cancelled(ident),
                             lambda p: update(ident, payload.get('progress_offset', 0) + payload.get('progress_scale', 1) * .88 * (elapsed + p * clip_length) / total,
                                               f'{gi}/{len(groups)} 영상 · 원본 렌더 중'),
                             asset_path(visual['id']) if visual else None, visual['metadata'] if visual else None)
                partial.replace(piece)
            pieces.append(piece)
            edit_list.append({'asset_id': asset['id'], 'source_name': asset['name'], 'label': label,
                              'original_start': clip['start'], 'original_end': clip['end'],
                              'edited_start': elapsed, 'edited_end': elapsed + clip_length, 'frame': clip.get('frame', {}),
                              'visual_asset_id': clip.get('visual_asset_id'), 'visual_source_name': visual['name'] if visual else None,
                              'visual_start': clip.get('visual_start',0)})
            elapsed += clip_length
        prefix = base if len(groups) == 1 else f'{gi:03}_{base}'
        output = target / f'{prefix}.mp4'
        concat = work / 'concat.txt'
        paths = [p.as_posix().replace("'", "'\\''") for p in pieces]
        concat.write_text(''.join("file '" + path + "'\n" for path in paths), encoding='utf-8')
        run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-f', 'concat', '-safe', '0', '-i', concat,
                    '-c', 'copy', '-movflags', '+faststart', output], work, lambda: is_cancelled(ident))
        rendered_info = probe(output)
        if abs(rendered_info['duration'] - (elapsed - group_start)) > .08:
            raise ValueError('렌더 길이가 편집 타임라인과 일치하지 않습니다. 구간 경계를 확인해 주세요.')
        file_list.append({'name': output.name, 'size': output.stat().st_size, 'label': label, 'type': 'video'})
        if not preview:
            local = timeline.local_captions(items, group_start, elapsed)
            if local or len(groups) == 1:
                subtitle = target / f'{prefix}.srt'
                subtitle.write_text(timeline.srt(local, elapsed - group_start), encoding='utf-8')
                file_list.append({'name': subtitle.name, 'size': subtitle.stat().st_size, 'label': label, 'type': 'subtitle'})
    if not preview:
        manifest = {'revision': payload['revision'], 'timeline_signature': timeline.signature(state), 'mode': payload['mode'],
                    'clips': edit_list, 'notice': '캡컷 프로젝트 파일이 아닌 참고·복원용 편집 목록입니다.'}
        atomic_json(target / 'edit-list.json', manifest)
        file_list.append({'name': 'edit-list.json', 'size': (target / 'edit-list.json').stat().st_size, 'type': 'manifest'})
        if len(groups) > 1 and items:
            combined = target / f'{base}_전체연결용.srt'
            combined.write_text(timeline.srt(items, total), encoding='utf-8')
            file_list.append({'name': combined.name, 'size': combined.stat().st_size, 'type': 'subtitle'})
        update(ident, .93, 'MP4·SRT·편집 목록 ZIP 생성 중')
        archive = target / f'{base}.zip'
        # ZIP_STORED avoids recompressing H.264; file data is copied in fixed-size blocks, including ZIP64.
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as zipped:
            for entry in list(file_list):
                with (target / entry['name']).open('rb') as source, zipped.open(entry['name'], 'w', force_zip64=True) as destination:
                    while chunk := source.read(1024 * 1024):
                        check_cancel(ident)
                        destination.write(chunk)
        file_list.append({'name': archive.name, 'size': archive.stat().st_size, 'type': 'archive'})
    return {'files': file_list, 'revision': payload['revision'], 'signature': timeline.signature(state),
            'render_signature': timeline.render_signature(state), 'preview': preview}


def auto_cut(ident, payload):
    """Acoustic silence, not speech VAD: keep audible food sounds and music."""
    asset = db.get_asset(payload['asset_id'])
    work = DATA / 'work' / ident
    work.mkdir(exist_ok=True)
    with db.connection() as conn:
        job = conn.execute('SELECT project_id,result FROM jobs WHERE id=?', (ident,)).fetchone()
    result = json.loads(job['result'])
    if not result.get('applied'):
        length = asset['metadata']['duration']
        update(ident, 0, '1/3 · 소리 크기로 무음 구간 찾는 중 · 자막 모델 불필요')
        run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-i', asset_path(asset['id']),
                    '-map', '0:a:0', '-vn', '-af',
                    f"silencedetect=noise={payload['threshold_db']}dB:d={payload['minimum']}",
                    '-f', 'null', '-'], work, lambda: is_cancelled(ident),
                   lambda p: update(ident, p * .3, '1/3 · 무음 구간 찾는 중'), length)
        gaps, start = [], None
        with (work / 'ffmpeg.log').open(encoding='utf-8', errors='replace') as log:
            for line in log:
                match = re.search(r'silence_(start|end):\s*([0-9.eE+-]+)', line)
                if not match:
                    continue
                value = max(0, min(length, float(match[2])))
                if match[1] == 'start':
                    start = value
                elif start is not None:
                    gaps.append([start, value])
                    start = None
        if start is not None:
            gaps.append([start, length])
        candidates = []
        for a, b in gaps:
            a = a + (payload['after'] if a > .001 else 0)
            b = b - (payload['before'] if b < length - .001 else 0)
            if b > a:
                candidates.append({'start': a, 'end': b})
        check_cancel(ident)
        update(ident, .32, '2/3 · 무음 자동 삭제 · 보존 구간 유지')
        with db.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT state,revision FROM projects WHERE id=?', (job['project_id'],)).fetchone()
            analysis = {**asset['analysis'], 'silence': {'gaps': gaps, 'candidates': candidates,
                        'threshold_db': payload['threshold_db'], 'minimum': payload['minimum']}}
            conn.execute('UPDATE assets SET analysis=? WHERE id=?', (json.dumps(analysis), asset['id']))
            if row['revision'] != payload['revision']:
                raise ValueError('분석 중 편집이 변경되어 자동 컷을 적용하지 않았어요. 최신 편집에서 다시 실행해 주세요.')
            if STOP.is_set() or conn.execute('SELECT cancel FROM jobs WHERE id=?', (ident,)).fetchone()['cancel']:
                raise Cancelled()
            before_state = json.loads(row['state'])
            state = timeline.apply_cuts(json.loads(row['state']), asset['id'], candidates)
            timeline.validate_state(state, {a['id']: db.get_asset(a['id']) for a in conn.execute('SELECT id FROM assets WHERE project_id=?', (job['project_id'],))})
            before_length, after_length = timeline.duration(before_state['clips']), timeline.duration(state['clips'])
            if after_length < 1 / state.get('fps', 30):
                raise ValueError('영상 전체가 무음으로 감지되어 원본을 유지했어요. 무음 기준을 더 낮추거나 보존 구간을 지정해 주세요.')
            if len(json.dumps(state, ensure_ascii=False).encode()) > 4 * 1024 * 1024:
                raise ValueError('편집 정보가 너무 커서 자동 컷을 적용하지 않았어요. 원본을 나눠 주세요.')
            revision = row['revision'] + 1
            result = {'applied': True, 'asset_id': asset['id'], 'before_seconds': before_length,
                      'after_seconds': after_length, 'removed_seconds': max(0, before_length - after_length),
                      'candidates': len(candidates), 'revision': revision,
                      'signature': timeline.signature(state), 'render_signature': timeline.render_signature(state),
                      'preview': True, 'files': []}
            # Save commit + snapshot atomically so a restart cannot apply the cuts twice.
            payload = {**payload, 'before_state': before_state, 'render_state': state}
            conn.execute('UPDATE projects SET state=?,revision=?,updated=? WHERE id=?',
                         (json.dumps(state, ensure_ascii=False), revision, time.time(), job['project_id']))
            conn.execute('UPDATE jobs SET payload=?,result=? WHERE id=?',
                         (json.dumps(payload, ensure_ascii=False), json.dumps(result), ident))
    state = payload['render_state']
    if result['after_seconds'] > MAX_OUTPUT_SECONDS:
        return {**result, 'notice': '자동 컷 적용 완료 · 편집본이 30분을 넘어서 타임라인으로 확인해 주세요. 제품별·컷별 출력이 가능합니다.'}
    # Cut changes invalidate previous caption timing; the silent-cut preview is text-free.
    preview_state = {**state, 'captions': {'items': []}}
    try:
        exported = render(ident, {'state': preview_state, 'revision': result['revision'],
                                 'mode': 'full', 'preview': True, 'filename': '무음_자동편집_미리보기',
                                 'progress_offset': .35, 'progress_scale': .65})
    except Cancelled:
        raise
    except Exception as exc:
        return {**result, 'notice': '자동 컷은 적용됐어요. 미리보기 파일 생성 실패: ' + str(exc)[:500]}
    return {**result, **exported}


def edit_script(ident, payload):
    with db.connection() as conn:
        job=conn.execute('SELECT project_id,result FROM jobs WHERE id=?',(ident,)).fetchone()
    result=json.loads(job['result'])
    if not result.get('applied'):
        for index, asset_id in enumerate(payload['speech_ids']):
            check_cancel(ident)
            asset=db.get_asset(asset_id)
            if not asset['analysis'].get('transcribed'):
                update(ident,0,f'{index+1}/{len(payload["speech_ids"])} · 실제 대사 인식: {asset["name"]}')
                analyze(ident,{'asset_id':asset_id,'transcribe':True,'model':payload['model'],
                               'script_asset_checkpoint':True,'vocabulary':'','names':[]})
        check_cancel(ident)
        assets={a:db.get_asset(a) for a in payload['asset_ids']}
        update(ident,.35,'대본 순서대로 실제 구간 연결 · 연출 적용')
        with db.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT state,revision FROM projects WHERE id=?',(job['project_id'],)).fetchone()
            if row['revision']!=payload['revision']:
                raise ValueError('대사 분석 중 편집이 변경되어 원본 편집을 유지했어요. 최신 상태에서 다시 실행해 주세요.')
            if STOP.is_set() or conn.execute('SELECT cancel FROM jobs WHERE id=?',(ident,)).fetchone()['cancel']:
                raise Cancelled()
            before=json.loads(row['state'])
            state=script_edit.assemble(script_edit.Brief.model_validate(payload['brief']),before,assets,payload['voice_mode'])
            result={'applied':bool(state['clips']), **state['script_edit'],'files':[],'preview':True,
                    'matched':sum(r['status']=='matched' for r in state['script_edit']['lines']),
                    'total':len(state['script_edit']['lines'])}
            if not state['clips']:
                return {**result,'notice':'일치하는 실제 대사가 없어 기존 편집을 유지했어요. 대본과 원음을 확인해 주세요.'}
            if len(json.dumps(state,ensure_ascii=False).encode())>4*1024*1024:
                raise ValueError('편집 정보가 너무 큽니다. 대본·원본을 나눠 주세요.')
            revision=row['revision']+1
            result.update(revision=revision,signature=timeline.signature(state),render_signature=timeline.render_signature(state),
                          before_seconds=timeline.duration(before['clips']),after_seconds=timeline.duration(state['clips']))
            payload={**payload,'before_state':before,'render_state':state}
            conn.execute('UPDATE projects SET state=?,revision=?,updated=? WHERE id=?',(json.dumps(state,ensure_ascii=False),revision,time.time(),job['project_id']))
            conn.execute('UPDATE jobs SET payload=?,result=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),json.dumps(result,ensure_ascii=False),ident))
    try:
        exported=render(ident,{'state':{**payload['render_state'],'captions':{'items':[]}},'revision':result['revision'],
                              'mode':'full','preview':True,'filename':'대본_자동편집_미리보기','progress_offset':.4,'progress_scale':.6})
    except Cancelled:
        raise
    except Exception as exc:
        return {**result,'notice':'대본 컷은 적용됐어요. 미리보기 파일 생성 실패: '+str(exc)[:500]}
    return {**result,**exported}


def loop():
    # One worker / one uvicorn process. Durable queued jobs survive a server restart.
    with db.connection() as conn:
        conn.execute("UPDATE jobs SET status='queued',message='서버 재시작 후 작업 재개' WHERE status='running'")
    while not STOP.wait(.3):
        with db.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:
                continue
            ident = row['id']
            conn.execute("UPDATE jobs SET status='running',updated=? WHERE id=?", (time.time(), ident))
        try:
            check_cancel(ident)
            payload = json.loads(row['payload'])
            result = {'ingest': ingest, 'analyze': analyze, 'render': render, 'auto_cut': auto_cut, 'script_edit': edit_script}[row['kind']](ident, payload)
            check_cancel(ident)
            db.update_job(ident, status='completed', progress=1, message='완료', result=result)
            shutil.rmtree(DATA / 'work' / ident, ignore_errors=True)
        except Cancelled:
            if STOP.is_set():
                db.update_job(ident, status='queued', message='서버가 다시 시작하면 재개합니다.')
            else:
                db.update_job(ident, status='cancelled', message='작업을 취소했습니다.')
                shutil.rmtree(DATA / 'work' / ident, ignore_errors=True)
            shutil.rmtree(DATA / 'exports' / ident, ignore_errors=True)
        except Exception as exc:
            db.update_job(ident, status='failed', message=str(exc)[:3000])
            shutil.rmtree(DATA / 'exports' / ident, ignore_errors=True)
            if row['kind'] == 'ingest':
                with db.connection() as conn:
                    conn.execute("UPDATE assets SET status='invalid' WHERE id=?", (json.loads(row['payload'])['asset_id'],))


def start():
    STOP.clear()
    thread = threading.Thread(target=loop, daemon=True, name='studio-worker')
    thread.start()
    return thread
