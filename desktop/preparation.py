import threading

from starlette.responses import JSONResponse
from starlette.routing import Route


class ModelPreparation:
    def __init__(self, prepare=None, load=None):
        self.prepare = prepare
        self.load = load
        self.lock = threading.Lock()
        self.status = 'waiting'
        self.phase = 'download'
        self.thread = None

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return False
            if self.status == 'ready':
                return False
            self.status = 'preparing'
            self.phase = 'download'
            self.thread = threading.Thread(target=self._run, daemon=True, name='desktop-model-setup')
            self.thread.start()
            return True

    def _run(self):
        try:
            if self.prepare is None:
                from scripts.download_model import ensure_model
                ensure_model()
            else:
                self.prepare()
            with self.lock:
                self.phase = 'loading'
            if self.load is None:
                from studio.worker import load_model
                load_model()
            else:
                self.load()
            with self.lock:
                self.status = 'ready'
        except Exception:
            import traceback
            traceback.print_exc()
            with self.lock:
                self.status = 'error'

    def snapshot(self):
        with self.lock:
            status, phase = self.status, self.phase
        messages = {
            'waiting': '한국어 자막 모델 준비를 시작합니다. 영상 업로드와 기획부터 사용할 수 있어요.',
            'preparing': ('받은 모델을 확인하고 있습니다. 영상 업로드와 기획은 먼저 사용할 수 있어요.'
                          if phase == 'loading' else '한국어 자막 모델을 준비하고 있습니다(처음 한 번, 약 1.5GB). 영상 업로드와 기획부터 사용할 수 있어요.'),
            'ready': '자막 모델 준비 완료 · 음성 인식을 사용할 수 있어요.',
            'error': '자막 모델을 준비하지 못했습니다. 인터넷 연결과 저장 공간을 확인한 뒤 다시 시도해 주세요.',
        }
        downloaded = 0
        if status == 'preparing' and phase == 'download':
            from studio.settings import DATA, MODEL_NAME
            staging = DATA / 'models' / f'.{MODEL_NAME}.download'
            try:
                for path in staging.rglob('*'):
                    if path.is_file():
                        downloaded += path.stat().st_size
            except OSError:
                pass  # Files can move while the verified download is activated.
        return {'status': status, 'phase': phase, 'message': messages[status],
                'downloaded_bytes': downloaded, 'can_retry': status == 'error'}


def install_preparation(app, preparation):
    app.state.desktop_setup = preparation

    async def status(request):
        return JSONResponse(preparation.snapshot())

    async def retry(request):
        started = preparation.start()
        return JSONResponse(preparation.snapshot(), status_code=202 if started else 409)

    app.router.routes[0:0] = [Route('/api/desktop/status', status, methods=['GET']),
                             Route('/api/desktop/retry', retry, methods=['POST'])]
