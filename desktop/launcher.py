"""Double-click launcher. Python, FFmpeg and the web UI are packaged in the EXE."""
import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path


def configure():
    bundle = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(bundle))
    home_data = Path(os.getenv('LOCALAPPDATA') or Path.home() / '.local' / 'share') / 'IyoringCutStudio'
    os.environ.setdefault('STUDIO_DATA_DIR', str(home_data))
    os.environ.setdefault('STUDIO_WHISPER_MODEL', 'medium')
    os.environ['PATH'] = str(bundle / 'ffmpeg' / 'bin') + os.pathsep + os.environ.get('PATH', '')
    os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
    os.environ.setdefault('HF_HOME', str(Path(os.environ['STUDIO_DATA_DIR']) / 'huggingface'))
    for stream in [sys.stdout, sys.stderr]:
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def smoke(base, entry):
    import httpx
    import numpy as np
    from studio.settings import DATA
    from studio.worker import load_model

    list(load_model().transcribe(np.zeros(32000, dtype=np.float32), language='ko', vad_filter=True)[0])
    with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
        assert client.get('/api/projects').status_code == 401
        assert client.get(entry).status_code == 303
        assert client.get(entry).status_code == 403
        cfg = client.get('/api/config').json()
        assert cfg['max_file_bytes'] == 10_000_000_000 and cfg['max_input_seconds'] == 7200
        assert cfg['model_name'] == 'medium' and cfg['model_ready']
        path = DATA / 'desktop-smoke-input.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'testsrc2=size=180x320:rate=30:duration=2', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000:duration=2', '-c:v', 'libx264',
                        '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)], check=True)
        project = client.post('/api/projects', json={'name': '실행 파일 검증'}).json()
        upload = client.post(f'/api/projects/{project["id"]}/uploads', json={'name': path.name, 'size': path.stat().st_size}).json()
        assert client.put(f'/api/uploads/{upload["id"]}/chunks/0', content=path.read_bytes()).status_code == 200

        def wait_job(ident):
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                jobs = client.get('/api/jobs').json()
                job = next(j for j in jobs if j['id'] == ident)
                if job['status'] in ['completed', 'failed', 'cancelled']:
                    assert job['status'] == 'completed', job['message']
                    return job
                time.sleep(.2)
            raise RuntimeError('실행 파일 출력 검증 시간 초과')

        wait_job(client.post(f'/api/uploads/{upload["id"]}/complete').json()['job_id'])
        project = client.get('/api/projects/' + project['id']).json()
        response = client.post('/api/projects/' + project['id'] + '/render', json={
            'revision': project['revision'], 'mode': 'full', 'preview': False, 'filename': 'desktop-smoke'})
        assert response.status_code == 200, response.text
        job = wait_job(response.json()['job_id'])
        video = next(f for f in job['result']['files'] if f['type'] == 'video')
        response = client.get('/api/exports/' + job['id'] + '/' + video['name'])
        assert response.status_code == 200 and len(response.content) > 1000
    print('Portable smoke passed: medium/VAD, 10GB/2h settings, auto-login/replay rejection, upload, MP4 export/download.')


def run(smoke_test=False):
    configure()
    from filelock import FileLock
    from studio.settings import DATA, MODEL_DIR
    with FileLock(DATA / 'desktop.lock', timeout=0):
        if not (MODEL_DIR / 'model.bin').is_file():
            print('첫 실행입니다. 한국어 자막 인식 모델(약 1.5GB)을 자동으로 준비합니다. 잠시 기다려 주세요.', flush=True)
        else:
            print('이요링 컷 스튜디오를 시작합니다.', flush=True)
        from studio.app import app
        from desktop.session import install_desktop_entry
        from desktop.preparation import ModelPreparation, install_preparation
        preparation = ModelPreparation()
        install_preparation(app, preparation)
        import uvicorn
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        base = 'http://127.0.0.1:' + str(listener.getsockname()[1])
        entry = install_desktop_entry(app)
        # Desktop access logs stay off: the one-time ticket is never logged.
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, proxy_headers=False, log_level='error', workers=1))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 30
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError('앱 시작에 실패했습니다. 이미 실행 중인지 확인해 주세요.')
                time.sleep(.1)
            if smoke_test:
                # The app must be usable BEFORE the model download is started.
                import httpx
                with httpx.Client(base_url=base, trust_env=False) as client:
                    assert client.get(entry).status_code == 303
                    assert client.get('/').status_code == 200
                    assert not client.get('/api/config').json()['model_ready']
                    assert client.get('/api/desktop/status').json()['status'] == 'waiting'
                    project = client.post('/api/projects', json={'name': '모델 준비 전 작업실'}).json()
                    assert project['id']
                print('Immediate startup passed: web UI and projects available before downloading the model.', flush=True)
                preparation.start()
                deadline = time.monotonic() + 900
                while preparation.snapshot()['status'] != 'ready':
                    if preparation.snapshot()['status'] == 'error' or time.monotonic() >= deadline:
                        raise RuntimeError('자막 모델 준비 검증에 실패했습니다.')
                    time.sleep(.2)
                entry = install_desktop_entry(app)
                smoke(base, entry)
            else:
                manual_entry = install_desktop_entry(app, ttl=600)
                try:
                    opened = webbrowser.open(base + entry)
                except OSError:
                    opened = False
                if not opened:
                    print('브라우저 자동 실행 요청을 보내지 못했습니다.', flush=True)
                print('브라우저 창이 안 보이면 아래 접속 주소를 Chrome 또는 Edge 주소창에 붙여 넣으세요:', flush=True)
                print('접속 주소: ' + base + manual_entry, flush=True)
                print('이 주소는 이 PC에서 10분 안에 한 번 사용할 수 있습니다.', flush=True)
                preparation.start()
                print('브라우저에서 작업하세요. 이 창을 닫거나 Ctrl+C를 누르면 앱이 종료됩니다.', flush=True)
                print('다시 실행하면 프로젝트와 원본을 이어서 사용할 수 있습니다.', flush=True)
                while thread.is_alive():
                    thread.join(.5)
        finally:
            server.should_exit = True
            thread.join(20)
            listener.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--smoke-test', action='store_true')
    args = parser.parse_args()
    try:
        run(args.smoke_test)
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback
        traceback.print_exc()
        if not args.smoke_test:
            input('실행에 실패했습니다. 위 오류를 확인한 뒤 Enter를 눌러 닫으세요.')
        raise SystemExit(1)
