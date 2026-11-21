"""'내 PC 파일 바로 연결' 화면 점검(서버 없이): 프로그램 안 폴더 탐색 → 영상 선택 → 연결 요청 형태를 확인한다."""
import http.server
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_guided_ui_mock as base_mock  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {**base_mock.CONFIG, 'desktop': True}
BROWSE = {
    '': {'path': '', 'parent': None, 'places': [{'name': '다운로드', 'path': 'C:\\Users\\u\\Downloads'}], 'dirs': [{'name': 'C:\\', 'path': 'C:\\'}], 'files': []},
    'C:\\Users\\u\\Downloads': {'path': 'C:\\Users\\u\\Downloads', 'parent': 'C:\\Users\\u', 'places': [],
                                'dirs': [{'name': '촬영', 'path': 'C:\\Users\\u\\Downloads\\촬영'}],
                                'files': [{'name': '1116 원본.mp4', 'path': 'C:\\Users\\u\\Downloads\\1116 원본.mp4', 'size': 4.3e9, 'mtime': 2},
                                          {'name': '더빙.m4a', 'path': 'C:\\Users\\u\\Downloads\\더빙.m4a', 'size': 2e6, 'mtime': 1}]},
}
sent = []


def handler(route):
    req = route.request
    path = req.url.split('/api', 1)[1].split('?')[0]
    if path == '/config':
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(CONFIG))
    if path == '/local-browse':
        from urllib.parse import parse_qs, urlparse
        key = parse_qs(urlparse(req.url).query).get('path', [''])[0]
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(BROWSE.get(key, BROWSE[''])))
    if path == '/projects' and req.method == 'POST':
        sent.append(('new', json.loads(req.post_data)['name']))
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(base_mock.PROJECT))
    if path.endswith('/local-files'):
        sent.append(json.loads(req.post_data))
        return route.fulfill(status=200, content_type='application/json', body=json.dumps({'job_ids': ['j9']}))
    return base_mock.handler_for(route)


def main():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT / 'web'), **k)

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        page = p.chromium.launch().new_page(viewport={'width': 1280, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/api/**', handler)
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
        page.wait_for_selector('#local-pick', state='visible', timeout=10000)
        page.click('#local-pick')
        page.wait_for_selector('#local-browser .lb-item', timeout=5000)
        assert '다운로드' in page.text_content('#lb-list')
        page.click('#lb-list [data-dir="C:\\\\Users\\\\u\\\\Downloads"]')
        page.wait_for_selector('#lb-list input[type=checkbox]', timeout=5000)
        assert page.locator('#lb-list input[type=checkbox]').count() == 2
        assert page.is_disabled('#lb-link')
        page.check('#lb-list input[data-file$="1116 원본.mp4"]')
        assert '1개' in page.text_content('#lb-link')
        page.click('#lb-link')
        page.wait_for_timeout(500)
        assert sent[-1] == {'paths': ['C:\\Users\\u\\Downloads\\1116 원본.mp4']}, sent
        assert sent[0] in (('new', '1116 원본'), sent[-1]), sent   # 열린 프로젝트가 없으면 파일 이름으로 새로 만든다
        assert not page.is_visible('#local-browser')
    server.shutdown()
    print('PC 파일 연결 화면 점검 통과 · JS 오류', len(errors), errors)
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
