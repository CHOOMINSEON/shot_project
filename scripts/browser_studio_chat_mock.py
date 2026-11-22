"""4칸 화면 + 편집 채팅 점검(서버 없이): 배치, 채팅 명령이 타임라인을 실제로 바꾸는지(PUT 요청 내용), 되돌리기."""
import http.server
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import browser_guided_ui_mock as base_mock  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
puts = []
state = {'project': json.loads(json.dumps(base_mock.PROJECT))}


def handler(route):
    req = route.request
    path = req.url.split('/api', 1)[1].split('?')[0]
    if req.method == 'PUT' and path == '/projects/p1':
        body = json.loads(req.post_data)
        puts.append(body['state']['clips'])
        p = state['project']
        p['state'] = body['state']
        p['revision'] = p['revision'] + 1
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(p))
    if path == '/projects/p1' and req.method == 'GET':
        return route.fulfill(status=200, content_type='application/json', body=json.dumps(state['project']))
    return base_mock.handler_for(route)


def main(shot):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT / 'web'), **k)

        def log_message(self, *a):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Quiet)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors = []
    with sync_playwright() as p:
        page = p.chromium.launch().new_page(viewport={'width': 1440, 'height': 900})
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/api/**', handler)
        page.goto(f'http://127.0.0.1:{server.server_address[1]}/')
        page.wait_for_selector('#guided-report .script-row', timeout=10000)
        # 배치: 채팅 왼쪽, 영상 가운데, 타임라인 영상 아래, 지침 오른쪽
        box = lambda s: page.locator(s).first.bounding_box()
        chat, video, tl, guide = box('#chat-panel'), box('section.viewer'), box('section.timeline'), box('#guided-text')
        assert chat['x'] < video['x'] < guide['x'], (chat, video, guide)
        assert tl['y'] > video['y'] and abs(tl['x'] - video['x']) < 5, (tl, video)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        n0 = page.evaluate('project.state.clips.length')
        def say(text):
            page.fill('#chat-input', text)
            page.press('#chat-input', 'Enter')
            page.wait_for_timeout(350)
            return page.locator('.chat-msg.bot').last.text_content()
        r = say('도움말')
        assert '3번 컷 지워' in r
        r = say('몇 개야?')
        assert f'구간 {n0}개' in r, r
        len0 = page.evaluate('project.state.clips[0].end-project.state.clips[0].start')
        r = say('1번 끝 0.5초 줄여')
        assert '줄였어요' in r, r
        assert abs(page.evaluate('project.state.clips[0].end-project.state.clips[0].start') - (len0 - .5)) < .04
        assert len(puts) == 1
        if n0 >= 2:
            a, b = page.evaluate('[project.state.clips[0].id, project.state.clips[1].id]')
            r = say('1번이랑 2번 바꿔')
            assert page.evaluate('[project.state.clips[0].id, project.state.clips[1].id]') == [b, a], r
        r = say('되돌려')
        assert '되돌렸' in r, r
        r = say(f'{n0 + 5}번 지워')
        assert '없어요' in r and 'error' in page.locator('.chat-msg.bot').last.get_attribute('class')
        r = say('오늘 날씨 어때')
        assert '잘 모르겠' in r
        r = say('마지막 컷 지워')
        assert '지웠어요' in r and page.evaluate('project.state.clips.length') == n0 - 1, r
        page.screenshot(path=shot)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(200)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), '모바일 가로 넘침'
    server.shutdown()
    print('4칸 화면·편집 채팅 점검 통과 · JS 오류', len(errors), errors)
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else '/home/claude/studio-chat.png'))
