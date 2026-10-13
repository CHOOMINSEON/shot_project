import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Disposable fixture credentials, not a production secret.
TEST_DATA = tempfile.TemporaryDirectory(prefix='iyoring-tests-')
os.environ['STUDIO_DATA_DIR'] = TEST_DATA.name
os.environ['STUDIO_PASSWORD'] = 'fixture-owner-password-only'

from studio.app import app


@pytest.fixture(scope='session')
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def owner(client):
    client.cookies.clear()
    assert client.post('/api/login', json={'password': 'fixture-owner-password-only'}).status_code == 200
    return client


@pytest.fixture(scope='session')
def sample(tmp_path_factory):
    import subprocess
    path = tmp_path_factory.mktemp('media') / 'sample.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=8',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=8',
                    '-af', "volume=enable='between(t,2,4)':volume=0", '-c:v', 'libx264', '-threads', '2',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(path)], check=True)
    return path


@pytest.fixture(scope='session',autouse=True)
def vision_runtime():
    """Reuse verified models if installed; CI obtains pinned public models once."""
    from studio import scene_models
    local=Path(__file__).resolve().parents[1]/'.data/models/scene-search-v1'
    if all((local/name).is_file() for name,*_ in scene_models.FILES):
        scene_models.DIRECTORY=local
    scene_models.ensure()
