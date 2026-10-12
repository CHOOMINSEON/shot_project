from fastapi.testclient import TestClient
import threading
import pytest

from desktop.session import install_desktop_entry
from studio.app import app
from desktop.preparation import ModelPreparation, install_preparation


@pytest.fixture
def setup_controller(client):
    release = threading.Event()
    controller = ModelPreparation(prepare=lambda: release.wait(10), load=lambda: None)
    routes = list(app.router.routes)
    install_preparation(app, controller)
    try:
        yield controller, release
    finally:
        release.set()
        if controller.thread:
            controller.thread.join(5)
        app.router.routes[:] = routes
        del app.state.desktop_setup


def test_desktop_preparation_does_not_block_work_and_requires_owner(owner, setup_controller):
    controller, release = setup_controller
    assert owner.get('/api/desktop/status').json()['status'] == 'waiting'
    assert not owner.get('/api/config').json()['model_ready']
    assert owner.post('/api/projects', json={'name': '설치 중에도 사용할 작업실'}).status_code == 200
    assert controller.start()
    assert not controller.start()
    assert owner.get('/api/desktop/status').json()['status'] == 'preparing'
    assert owner.post('/api/desktop/retry').status_code == 409
    assert owner.post('/api/desktop/retry', headers={'Origin': 'https://other.example'}).status_code == 403
    owner.cookies.clear()
    assert owner.get('/api/desktop/status').status_code == 401
    release.set()
    controller.thread.join(5)
    assert controller.snapshot()['status'] == 'ready'


def test_desktop_model_failure_can_retry(owner, setup_controller):
    controller, _ = setup_controller
    attempts = []

    def prepare():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError('fixture download failed')

    controller.prepare = prepare
    controller.start()
    controller.thread.join(5)
    result = owner.get('/api/desktop/status').json()
    assert result['status'] == 'error' and result['can_retry']
    assert 'fixture download failed' not in result['message']
    assert owner.post('/api/desktop/retry').status_code == 202
    controller.thread.join(5)
    assert owner.get('/api/desktop/status').json()['status'] == 'ready'
    assert owner.get('/api/config').json()['model_ready']


def test_desktop_preparation_reports_partial_download(owner, setup_controller):
    from studio.settings import DATA, MODEL_NAME
    controller, _ = setup_controller
    partial = DATA / 'models' / f'.{MODEL_NAME}.download' / 'weights.incomplete'
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(b'partial model bytes')
    try:
        controller.start()
        assert owner.get('/api/desktop/status').json()['downloaded_bytes'] >= partial.stat().st_size
    finally:
        partial.unlink()


def test_desktop_preparing_blocks_transcription_not_upload(owner, setup_controller, sample):
    from test_app import upload_video
    project, ident = upload_video(owner, sample)
    assert owner.post('/api/projects/' + project['id'] + '/analyze',
                      json={'asset_id': ident, 'transcribe': True}).status_code == 503


def test_desktop_ticket_is_local_single_use_and_preserves_auth(client):
    path = install_desktop_entry(app)
    remote = TestClient(app, base_url='http://127.0.0.1', client=('192.0.2.1', 40000))
    assert remote.get(path).status_code == 403


def test_desktop_ticket_flow(client):
    # Do not start a second lifespan: the session fixture owns the worker lock.
    local = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 40000))
    path = install_desktop_entry(app)
    assert local.get('/api/projects').status_code == 401
    assert local.get(path + 'invalid').status_code == 403
    response = local.get(path, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/'
    assert 'HttpOnly' in response.headers['set-cookie']
    assert local.get('/api/projects').status_code == 200
    assert local.get(path).status_code == 403
    assert local.post('/api/logout').status_code == 200
    assert local.get('/api/projects').status_code == 401


def test_desktop_ticket_expiry_and_hostname(client):
    local = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 40000))
    assert local.get(install_desktop_entry(app, ttl=0)).status_code == 403
    wrong_host = TestClient(app, base_url='http://other.example', client=('127.0.0.1', 40000))
    assert wrong_host.get(install_desktop_entry(app)).status_code == 403


def test_manual_start_ticket_survives_automatic_browser_entry(client):
    local = TestClient(app, base_url='http://127.0.0.1', client=('127.0.0.1', 40000))
    automatic = install_desktop_entry(app)
    manual = install_desktop_entry(app, ttl=600)
    assert local.get(automatic, follow_redirects=False).status_code == 303
    assert local.get(automatic).status_code == 403
    # A user can choose another browser when the default browser stays hidden.
    local.cookies.clear()
    assert local.get(manual, follow_redirects=False).status_code == 303
    assert local.get('/api/projects').status_code == 200
    assert local.get(manual).status_code == 403
