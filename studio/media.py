import json
import math
import os
import queue
import signal
import subprocess
import threading
import time
from pathlib import Path

from .settings import JOB_TIMEOUT, MAX_INPUT_SECONDS, THREADS


class Cancelled(Exception):
    pass


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                             '-show_format', '-show_streams', '-of', 'json', str(path)],
                            capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('영상을 읽을 수 없습니다. 정상적인 MP4·MOV·WebM 파일인지 확인해 주세요.')
    info = json.loads(result.stdout)
    streams = info.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not video:
        raise ValueError('영상 스트림이 없습니다.')
    duration = float(info.get('format', {}).get('duration', video.get('duration', 0)))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('영상 길이를 확인할 수 없습니다.')
    if duration > MAX_INPUT_SECONDS + .001:
        raise ValueError('원본 영상은 파일당 최대 2시간입니다. 촬영 영상을 나눠 업로드해 주세요.')
    if not any(f in info.get('format', {}).get('format_name', '').split(',')
               for f in ['mov', 'mp4', 'matroska', 'webm', 'avi', 'mpegts', 'mpeg', 'mxf']):
        raise ValueError('MP4·MOV·WebM 등 일반 영상 컨테이너만 지원합니다.')
    rotation = 0
    dolby = False
    for side in video.get('side_data_list', []):
        rotation = side.get('rotation', rotation)
        dolby |= 'DOVI' in side.get('side_data_type', '').upper()
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), {})
    return {'duration': duration, 'width': video['width'], 'height': video['height'],
            'rotation': rotation, 'fps': video.get('avg_frame_rate'), 'codec': video.get('codec_name'),
            'transfer': video.get('color_transfer', 'unknown'), 'colorspace': video.get('color_space', 'unknown'),
            'primaries': video.get('color_primaries', 'unknown'), 'dolby_vision': dolby,
            'has_audio': bool(audio), 'sample_rate': audio.get('sample_rate'),
            'hdr': video.get('color_transfer') in ['smpte2084', 'arib-std-b67'],
            'hdr_warning': 'Dolby Vision 동적 메타데이터는 지원하지 않습니다. 기본 영상의 색을 확인해 주세요.' if dolby else ''}


def run_ffmpeg(args, work, cancelled=lambda: False, progress=lambda _: None, expected_seconds=0):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    log = work / 'ffmpeg.log'
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-y', '-threads', str(THREADS),
               '-filter_threads', str(THREADS), '-filter_complex_threads', str(THREADS),
               '-progress', 'pipe:1', '-nostats'] + [str(a) for a in args]
    start = time.monotonic()
    with log.open('wb') as errors:
        # Windows cannot select anonymous subprocess pipes. A bounded reader queue
        # also keeps cancellation and timeouts responsive on all supported systems.
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors,
                                   start_new_session=os.name != 'nt',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0)
        lines = queue.Queue(maxsize=128)
        stopped = threading.Event()

        def read_progress():
            for line in iter(process.stdout.readline, b''):
                while not stopped.is_set():
                    try:
                        lines.put(line, timeout=.3)
                        break
                    except queue.Full:
                        continue
                if stopped.is_set():
                    break

        reader = threading.Thread(target=read_progress, daemon=True, name='ffmpeg-progress')
        reader.start()
        try:
            while process.poll() is None:
                if cancelled():
                    raise Cancelled('작업을 취소했습니다.')
                if time.monotonic() - start > JOB_TIMEOUT:
                    raise ValueError('작업 실행 제한 시간을 넘었습니다. 더 작은 구간으로 나누거나 서버 작업 제한을 조정해 주세요.')
                try:
                    line = lines.get(timeout=.3)
                except queue.Empty:
                    continue
                if line.startswith(b'out_time_us=') and expected_seconds:
                    try:
                        progress(min(.999, int(line.split(b'=')[1]) / 1e6 / expected_seconds))
                    except ValueError:
                        pass
            if process.returncode:
                with log.open('rb') as file:
                    file.seek(max(0, log.stat().st_size - 4000))
                    tail = file.read(4000).decode('utf-8', errors='replace')
                raise ValueError('FFmpeg 처리 실패: ' + tail[-2000:])
        finally:
            stopped.set()
            if process.poll() is None:
                if os.name == 'nt':
                    process.terminate()
                else:
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            reader.join(timeout=5)
            process.stdout.close()
    progress(1)


def color_filter(metadata):
    if metadata.get('hdr'):
        return 'zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p'
    return 'format=yuv420p'


def frame_filter(metadata, frame, width, height, fps):
    # FFmpeg autorotation happens before these filters. Position is intentionally manual.
    mode = frame.get('mode', 'fit')
    common = f'{color_filter(metadata)},fps={fps},setsar=1'
    if mode == 'fill':
        zoom = frame.get('zoom', 1)
        return f"{common},scale=w={int(width * zoom) // 2 * 2}:h={int(height * zoom) // 2 * 2}:force_original_aspect_ratio=increase,crop={width}:{height}:(iw-ow)*{frame.get('x', .5)}:(ih-oh)*{frame.get('y', .5)}"
    if mode == 'blur':
        return (f'{common},split=2[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase,'
                f'crop={width}:{height},boxblur=20:2[back];[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[front];'
                '[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1')
    return f'{common},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x111827'


def render_piece(source, clip, metadata, output, work, fps, quality, preview, cancelled, progress):
    width, height = (360, 640) if preview else (1080, 1920)
    length = clip['end'] - clip['start']
    args = ['-protocol_whitelist', 'file,pipe', '-ss', str(clip['start']), '-i', source]
    if not metadata['has_audio']:
        args += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=48000']
    args += ['-t', str(length), '-map', '0:v:0', '-map', '0:a:0' if metadata['has_audio'] else '1:a:0',
             '-vf', frame_filter(metadata, clip.get('frame', {}), width, height, fps),
             '-af', f'aresample=48000:async=1:first_pts=0,apad,afade=t=in:d=0.005,afade=t=out:st={max(0, length - .005)}:d=0.005',
             '-c:v', 'libx264', '-preset', 'ultrafast' if preview else 'fast', '-crf', '25' if preview else ('18' if quality == 'high' else '21'),
             '-maxrate', '30M' if quality == 'high' else '20M', '-bufsize', '60M' if quality == 'high' else '40M',
             '-pix_fmt', 'yuv420p', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
             '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-threads', str(THREADS),
             '-map_metadata', '-1', '-movflags', '+faststart', output]
    run_ffmpeg(args, work, cancelled, progress, length)
