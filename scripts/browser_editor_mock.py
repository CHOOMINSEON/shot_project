"""타임라인 편집 화면 점검(서버 없이): 실제 Chromium에서 자르기·삭제·순서 변경·끝점 조절·단축키가 올바른 저장 요청을 보내는지 확인한다.
실제 영상 재생은 검증하지 않는다(재생 위치는 테스트에서 지정). 실행: python scripts/browser_editor_mock.py
"""
import copy
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSET = {'id': 'v', 'name': '원본.mp4', 'status': 'ready', 'size': 1, 'created': 1, 'analysis': {'words': [], 'speech': []},
         'metadata': {'duration': 60, 'has_video': True, 'has_audio': True, 'width': 1080, 'height': 1920}}
CLIPS = [{'id': f'c{i}', 'asset_id': 'v', 'start': s, 'end': e, 'label': f'구간{i}', 'frame': {'mode': 'fit', 'x': .5, 'y': .5, 'zoom': 1}}
         for i, (s, e) in enumerate([(0, 10), (20, 30), (40, 50)])]
state = {'clips': copy.deepcopy(CLIPS), 'protections': [], 'fps': 30, 'quality': 'standard', 'captions': {'items': []}, 'scene_products': []}
puts = []
revision = [1]


def project():
    return {'id': 'p1', 'name': '테스트', 'revision': revision[0], 'state': state, 'assets': [ASSET],
            'duration': sum(c['end'] - c['start'] for c in state['clips']), 'signature': 's', 'render_signature': 'r'}


CONFIG = {'max_file_bytes': 10 ** 10, 'max_input_seconds': 7200, 'max_output_seconds': 1800, 'chunk_bytes': 8388608, 'model_ready': True,
          'model_name': 'medium', 'device': 'cpu', 'free_bytes': 10 ** 11, 'desktop': False, 'privacy': ''}


def handler(route):
    req = route.request
    path = req.url.split('/api', 1)[1].split('?')[0]
    data = {'/config': CONFIG, '/projects': [{'id': 'p1', 'name': '테스트', 'revision': 1, 'updated': 1}], '/jobs': [],
            '/guided/defaults': {'guideline': 'x', 'guidelines': {'default': 'x', 'commentary': 'y'}, 'styles': []}}.get(path)
    if path == '/projects/p1':
        if req.method == 'PUT':
            body = json.loads(req.post_data)
            state.clear()
            state.update(body['state'])
            revision[0] += 1
            puts.append(copy.deepcopy(body['state']['clips']))
        data = project()
    route.fulfill(status=200 if data is not None else 404, content_type='application/json', body=json.dumps(data if data is not None else {'detail': 'none'}))


def ids():
    return [c['id'] for c in state['clips']]


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
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1400, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/api/**', handler)
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
        page.wait_for_selector('.timeline-clip')
        assert page.locator('.timeline-clip').count() == 3
        page.evaluate("""() => { window.__t = 25; Object.defineProperty(document.getElementById('player'), 'currentTime', {get: () => window.__t, set: v => { window.__t = v; }, configurable: true}); }""")

        def settle():
            page.wait_for_timeout(250)

        # 1) 구간 선택 후 재생 위치(25초)에서 자르기: 두 번째 구간(20~30)이 20~25, 25~30으로 나뉨
        page.click('[data-clip="1"] ', position={'x': 12, 'y': 8})
        page.evaluate("window.__t = 25")
        page.keyboard.press('s')
        settle()
        assert [(c['start'], c['end']) for c in state['clips']] == [(0, 10), (20, 25), (25, 30), (40, 50)], state['clips']
        # 2) 되돌리기(Ctrl+Z)
        page.keyboard.press('Control+z')
        settle()
        assert len(state['clips']) == 3
        # 3) 앞/뒤 삭제: 세 번째 구간(40~50)에서 45초 기준
        page.click('[data-clip="2"] ', position={'x': 12, 'y': 8})
        page.evaluate("window.__t = 45")
        page.keyboard.press('q')
        settle()
        assert (state['clips'][2]['start'], state['clips'][2]['end']) == (45, 50), state['clips'][2]
        page.evaluate("window.__t = 47")
        page.keyboard.press('w')
        settle()
        assert (state['clips'][2]['start'], state['clips'][2]['end']) == (45, 47), state['clips'][2]
        # 4) 범위 밖 재생 위치에서는 자르지 않고 오류를 안내
        before = len(puts)
        page.evaluate("window.__t = 5")
        page.keyboard.press('s')
        settle()
        assert len(puts) == before and '구간 안' in page.text_content('#toast')
        # 5) 끌어서 순서 변경: 첫 구간을 맨 뒤로
        page.drag_and_drop('[data-clip="0"]', '[data-clip="2"]', source_position={'x': 30, 'y': 8}, target_position={'x': 90, 'y': 8})
        settle()
        assert ids() == ['c1', 'c2', 'c0'], ids()
        # 6) 오른쪽 끝을 끌어서 길이 조절(구간 폭의 절반만큼 → 길이 +50%)
        box = page.locator('[data-clip="0"]').bounding_box()
        old = state['clips'][0]['end'] - state['clips'][0]['start']
        handle = page.locator('[data-clip="0"] .trim-r').bounding_box()
        page.mouse.move(handle['x'] + 3, handle['y'] + 10)
        page.mouse.down()
        page.mouse.move(handle['x'] + 3 + box['width'] / 2, handle['y'] + 10, steps=5)
        page.mouse.up()
        settle()
        grown = state['clips'][0]['end'] - state['clips'][0]['start']
        assert abs(grown - old * 1.5) < old * .1 and grown <= 40, (old, grown)
        # 7) Shift 클릭으로 두 구간 선택 후 Delete → 한 번에 삭제
        page.click('[data-clip="1"] ', position={'x': 12, 'y': 8})
        page.keyboard.down('Shift')
        page.click('[data-clip="2"] ', position={'x': 12, 'y': 8})
        page.keyboard.up('Shift')
        page.keyboard.press('Delete')
        settle()
        assert len(state['clips']) == 1, ids()
        # 8) 입력창에서는 단축키가 동작하지 않는다
        before = len(puts)
        page.fill('#project-name', 'sdq')
        assert len(puts) == before
        browser.close()
    server.shutdown()
    print('편집 화면 점검 통과 · JS 오류', len(errors), errors[:3])
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
