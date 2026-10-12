from fastapi.testclient import TestClient

from desktop.session import install_desktop_entry
from studio.app import app


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
