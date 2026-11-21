import io
import json
import sys
import zipfile

from desktop import updater


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_zip(sha, deps, marker):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('studio/__init__.py', '')
        z.writestr('studio/_build.py', f"SHA = '{sha}'\nDEPS = '{deps}'\n")
        z.writestr('studio/marker.py', f'VALUE = {marker!r}\n')
        z.writestr('web/index.html', '<!doctype html>')
    return buf.getvalue()


def fake_net(monkeypatch, tag, blob):
    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, 'full_url') else req
        if 'releases/latest' in url:
            return Resp(json.dumps({'tag_name': tag, 'assets': [{'name': updater.ASSET, 'browser_download_url': 'https://x/u.zip'}]}).encode())
        return Resp(blob)
    monkeypatch.setattr(updater.urllib.request, 'urlopen', urlopen)


def test_code_update_is_downloaded_applied_and_imported(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, 'bundled_build', lambda: {'sha': 'aaaaaaaa0000', 'deps': 'D1'})
    fake_net(monkeypatch, 'desktop-windows-bbbbbbbb', make_zip('bbbbbbbb1111', 'D1', 'new'))
    saved_meta, saved_mods = list(sys.meta_path), {k: v for k, v in sys.modules.items() if k.split('.')[0] == 'studio'}
    try:
        root = updater.check_and_apply(tmp_path, log=lambda m: None)
        assert root == tmp_path / 'app-update' / 'current'
        import studio.marker
        assert studio.marker.VALUE == 'new'
        assert (root / 'web' / 'index.html').is_file()
    finally:
        sys.meta_path[:] = saved_meta
        for k in [k for k in sys.modules if k.split('.')[0] == 'studio']:
            del sys.modules[k]
        sys.modules.update(saved_mods)


def test_update_needing_new_libraries_is_not_applied(tmp_path, monkeypatch):
    logs = []
    monkeypatch.setattr(updater, 'bundled_build', lambda: {'sha': 'aaaaaaaa0000', 'deps': 'D1'})
    fake_net(monkeypatch, 'desktop-windows-cccccccc', make_zip('cccccccc2222', 'D2', 'x'))
    assert updater.check_and_apply(tmp_path, log=logs.append) is None
    assert any('전체 zip' in m for m in logs)
    assert not (tmp_path / 'app-update' / 'current').exists()


def test_offline_or_local_build_just_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, 'bundled_build', lambda: None)
    assert updater.check_and_apply(tmp_path) is None            # 개발 실행(버전 정보 없음)은 업데이트 안 함
    monkeypatch.setattr(updater, 'bundled_build', lambda: {'sha': 'a', 'deps': 'D1'})
    def boom(*a, **k):
        raise OSError('offline')
    monkeypatch.setattr(updater.urllib.request, 'urlopen', boom)
    assert updater.check_and_apply(tmp_path, log=lambda m: None) is None
