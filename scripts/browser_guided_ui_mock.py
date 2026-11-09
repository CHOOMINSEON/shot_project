"""지침 자동 편집 화면 점검(서버 없이): 정적 파일 + 가짜 API로 실제 Chromium에서 화면을 그린다.

실제 서버·모델·영상 처리는 검증하지 않는다. 화면의 JS 오류, 보고서 렌더링, 버튼 동작(요청 형태)만 확인한다.
실행: python scripts/browser_guided_ui_mock.py [스크린샷 경로]
"""
import http.server
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('STUDIO_DATA_DIR', tempfile.mkdtemp(prefix='guided-ui-'))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from studio import guided, timeline  # noqa: E402
from test_guided import asset, frame, review_words, tokens, w  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

V = asset(review_words())
V['size'] = 1000
frames = [frame(0, 12, 13, {'crosssection': .3}), frame(1, 13, 16, {'crosssection': .3}), frame(2, 16, 19, {'eating': .3}, shot=1)]
rules = guided.parse_guideline(guided.DEFAULT_GUIDELINE, 'oneshot')
plan = guided.plan([V], rules, {'v': frames}, {})
N = {'id': 'n', 'name': '나레이션.wav', 'status': 'ready', 'size': 10, 'created': 2, 'analysis': {'words': tokens([w(1, ' 먼저 우유를 붓고 돌려요.', 1, 4)])},
     'metadata': {'duration': 30, 'has_video': False, 'has_audio': True}}
lines = guided.narration_lines(N)
lines[0]['suggestions'] = [{'id': 'v:000000012000000', 'asset_id': 'v', 'filename': '원본.mp4', 'start': 12, 'end': 15, 'match_type': '의미 일치',
                            'thumbnail': '/none.jpg', 'selection_reason': ['단면 후보'], 'uncertainties': ['원본 확인 필요']}]
report = {k: plan[k] for k in ['units', 'removed', 'moved', 'warnings', 'missing', 'review', 'seconds', 'target', 'style', 'applied', 'unapplied']}
report.update(style_name='원테이크 먹방 리뷰', style_note='', detected={'style': 'oneshot', 'confidence': .7, 'reasons': ['영상 1개']}, narration=lines, narration_expected=True)
state = {'clips': plan['clips'], 'protections': [], 'fps': 30, 'quality': 'standard', 'captions': {'items': []}, 'scene_products': [], 'guided': report}
sig = timeline.signature(state)
V2 = {**asset(review_words(), ident='v2', name='먹방소리.mp4'), 'created': 1, 'size': 1000}
PROJECT = {'id': 'p1', 'name': '테스트', 'revision': 5, 'state': state, 'assets': [{**V, 'created': 1}, V2, N], 'duration': timeline.duration(state['clips']),
           'signature': sig, 'render_signature': timeline.render_signature(state)}
JOB = {'id': 'j1', 'project_id': 'p1', 'kind': 'guided_edit', 'status': 'completed', 'progress': 1, 'message': '완료', 'created': 1, 'updated': 2,
       'result': {'applied': True, **report, 'files': [], 'preview': True, 'revision': 5, 'signature': sig, 'render_signature': PROJECT['render_signature']}}
CONFIG = {'max_file_bytes': 10_000_000_000, 'max_input_seconds': 7200, 'max_output_seconds': 1800, 'chunk_bytes': 8388608, 'model_ready': True,
          'model_name': 'medium', 'device': 'cpu', 'free_bytes': 10 ** 11, 'desktop': False, 'privacy': ''}
GUIDED = {'guideline': guided.DEFAULT_GUIDELINE,
          'styles': [{'key': k, 'name': v['name'], 'note': v['note'], 'target': list(v['target']), 'narration': v['narration']} for k, v in guided.STYLES.items()]}
requests = []


def handler_for(route):
    req = route.request
    path = req.url.split('/api', 1)[1].split('?')[0]
    body = req.post_data
    requests.append((req.method, path, json.loads(body) if body else None))
    data = {'/config': CONFIG, '/projects': [{'id': 'p1', 'name': '테스트', 'revision': 5, 'updated': 1}], '/projects/p1': PROJECT,
            '/jobs': [JOB], '/guided/defaults': GUIDED}.get(path)
    if req.method == 'POST' and path.endswith('/guided-edit'):
        data = {'job_id': 'j2'}
    if req.method == 'POST' and path.endswith('/narration'):
        data = PROJECT
    if req.method == 'PUT':
        data = PROJECT
    route.fulfill(status=200 if data is not None else 404, content_type='application/json', body=json.dumps(data if data is not None else {'detail': 'none'}))


def main(shot):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT / 'web'), **k)

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_address[1]}/'
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 1000}, device_scale_factor=1)
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: m.type == 'error' and 'Failed to load resource' not in m.text and errors.append(m.text))
        page.route('**/api/**', handler_for)
        missing = []
        page.on('response', lambda r: r.status == 404 and missing.append(r.url.replace(base, '/')))
        page.goto(base)
        page.wait_for_selector('#guided-report .script-row', timeout=10000)
        assert page.input_value('#guided-text').startswith('업로드한 음식 리뷰 영상'), '기본 지침이 보여야 함'
        assert page.locator('#guided-style option').count() == 6
        assert page.locator('#guided-report .script-row.matched, #guided-report .script-row.missing').count() >= 8
        text = page.text_content('#guided-report')
        for expected in ['말실수 재시도', '반복 설명', '촬영 준비·대기', '장면 선택 필요', '찾지 못한 항목']:
            assert expected in text, expected
        assert page.is_enabled('#guided-start') and page.is_enabled('#guided-download')
        # 시작 버튼은 지침·유형·화면 옵션을 서버에 보낸다
        page.select_option('#guided-style', 'recipe')
        page.select_option('#guided-frame', 'blur')
        page.check('[data-g-audio="v2"]')
        page.click('#guided-start')
        page.wait_for_timeout(500)
        post = next(b for m, pth, b in requests if m == 'POST' and pth.endswith('/guided-edit'))
        assert post['style'] == 'recipe' and post['frame'] == 'blur' and '남길 장면' in post['guideline'] and post['revision'] == 5 and post['audio_source_ids'] == ['v2']
        # 나레이션 후보 연결 요청
        page.click('[data-g-link="0"]')
        page.wait_for_timeout(500)
        link = next(b for m, pth, b in requests if m == 'POST' and pth.endswith('/narration'))
        assert link['line'] == 0 and link['candidate_id'] == 'v:000000012000000'
        # 삭제 구간 복원은 타임라인 저장 요청(PUT)으로 이어진다
        before = sum(1 for m, *_ in requests if m == 'PUT')
        page.click('summary:has-text("삭제한 구간")')   # 접힌 목록을 사용자가 펼침
        page.click('[data-g-restore="0"]')
        page.wait_for_timeout(500)
        assert sum(1 for m, *_ in requests if m == 'PUT') > before
        # 고급 메뉴로 접힌 기존 대본 매칭이 남아 있음
        assert page.locator('details:has(#edit-script) > summary').inner_text().startswith('고급')
        overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        page.screenshot(path=shot, full_page=False)
        page.set_viewport_size({'width': 390, 'height': 900})
        mobile_overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
        browser.close()
    server.shutdown()
    print('404 응답(가짜 API에 없는 주소):', sorted(set(missing)))
    print('화면 점검 통과 · JS 오류', len(errors), errors[:3], '· 데스크톱 가로 넘침', overflow, '· 모바일 390px 가로 넘침', mobile_overflow)
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(Path(tempfile.gettempdir()) / 'guided-ui.png')))
