"""코드만 바뀐 새 버전을 자동으로 받아 쓰는 작은 업데이터(표준 라이브러리만 사용).

전체 앱(약 1.5GB)을 다시 받지 않도록, 빌드마다 프로그램 코드(studio·web·desktop, 약 1MB)만 담은
IyoringCutStudio-update.zip을 릴리스에 함께 올린다. 실행할 때 최신 릴리스를 확인해 코드만 받아
데이터 폴더(app-update)에 풀고, 설치된 앱의 코드 대신 그것을 불러온다.
필요한 라이브러리 목록(requirements.lock)이 바뀐 업데이트는 적용하지 않고 전체 새 버전을 받으라고 알린다.
"""
import importlib.abc
import importlib.machinery
import io
import json
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = 'CHOOMINSEON/shot_project'
ASSET = 'IyoringCutStudio-update.zip'
PACKAGES = ('studio', 'desktop')


def bundled_build():
    try:
        from studio import _build
        return {'sha': _build.SHA, 'deps': _build.DEPS}
    except Exception:
        return None


def _read_build(folder):
    info = {}
    try:
        for line in (folder / 'studio' / '_build.py').read_text(encoding='utf-8').splitlines():
            if '=' in line:
                k, v = line.split('=', 1)
                info[k.strip().lower()] = v.strip().strip('\'"')
    except OSError:
        return None
    return info if info.get('sha') and info.get('deps') else None


class _UpdateFinder(importlib.abc.MetaPathFinder):
    """업데이트 폴더의 studio·desktop 모듈을 설치된 앱의 것보다 먼저 찾는다."""

    def __init__(self, root):
        self.root = str(root)

    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] not in PACKAGES or name == 'desktop.launcher' or name == 'desktop.updater':
            return None
        search = [self.root] if '.' not in name else [str(Path(self.root, *name.split('.')[:-1]))]
        return importlib.machinery.PathFinder.find_spec(name, search)


def check_and_apply(data_dir, log=print, timeout=6):
    """최신 코드 업데이트를 받아 적용한다. 반환: 적용된 업데이트 폴더(없으면 None)."""
    base = bundled_build()
    if not base or os.getenv('STUDIO_NO_UPDATE') == '1':
        return None
    store = Path(data_dir) / 'app-update'
    store.mkdir(parents=True, exist_ok=True)
    current = store / 'current'
    try:
        req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases/latest',
                                     headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'IyoringCutStudio'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            release = json.load(r)
        asset = next((a for a in release.get('assets', []) if a.get('name') == ASSET), None)
        tag_sha = release.get('tag_name', '').rsplit('-', 1)[-1]
        have = _read_build(current) if current.is_dir() else None
        have_sha = (have or base)['sha']
        if asset and tag_sha and not have_sha.startswith(tag_sha) and not base['sha'].startswith(tag_sha):
            log('새 버전 코드를 받는 중이에요(약 1MB)…')
            with urllib.request.urlopen(urllib.request.Request(asset['browser_download_url'], headers={'User-Agent': 'IyoringCutStudio'}), timeout=60) as r:
                blob = r.read()
            staging = store / 'incoming'
            shutil.rmtree(staging, ignore_errors=True)
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for member in z.namelist():
                    target = (staging / member).resolve()
                    if not str(target).startswith(str(staging.resolve())):
                        raise ValueError('잘못된 업데이트 파일')
                z.extractall(staging)
            got = _read_build(staging)
            if not got:
                raise ValueError('업데이트 파일에 버전 정보가 없어요')
            if got['deps'] != base['deps']:
                shutil.rmtree(staging, ignore_errors=True)
                log('새 버전은 프로그램 구성 요소가 바뀌어서 자동 업데이트가 안 돼요. GitHub에서 전체 zip을 한 번 새로 받아 주세요.')
            else:
                shutil.rmtree(store / 'previous', ignore_errors=True)
                if current.is_dir():
                    current.rename(store / 'previous')
                staging.rename(current)
                log(f'새 버전 코드({got["sha"][:8]})를 적용했어요.')
    except Exception as exc:   # 인터넷이 없거나 GitHub 응답이 없어도 그냥 지금 버전으로 실행
        log(f'업데이트 확인을 건너뛰었어요({type(exc).__name__}). 지금 버전으로 실행해요.')
    have = _read_build(current) if current.is_dir() else None
    if have and have['deps'] == base['deps'] and have['sha'] != base['sha']:
        for name in [m for m in sys.modules if m.split('.')[0] == 'studio']:
            del sys.modules[name]   # 버전 확인에 쓴 설치본 모듈을 지우고 업데이트 코드를 다시 불러온다
        sys.meta_path.insert(0, _UpdateFinder(current))
        return current
    return None
