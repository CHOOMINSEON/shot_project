"""Synthetic footage: verifies planning, suggested corrections and real edit/render integration."""
import json
import os
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.settings import DATA

errors = []
project_name = '숏폼 기획·오타 검수 ' + uuid.uuid4().hex[:6]
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=os.getenv('CHROMIUM_BIN', '/usr/bin/chromium'),
                                         headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(os.getenv('STUDIO_TEST_URL', 'http://127.0.0.1:8000'))
    page.locator('#password').fill(os.getenv('STUDIO_PASSWORD') or (DATA / 'owner-password').read_text().strip())
    page.locator('#login-form button').click()
    page.wait_for_function("() => !document.querySelector('#login-dialog').open")
    page.on('dialog', lambda dialog: dialog.accept(project_name))
    page.locator('#new-project').click()
    page.wait_for_function("(name) => document.querySelector('#workspace-name').textContent === name", arg=project_name)
    page.locator('#upload').set_input_files('/tmp/iyoring-sample.mp4')
    page.wait_for_function("() => document.querySelectorAll('[data-clip]').length === 1", timeout=30000)
    page.locator('#advanced-edit').evaluate('(e) => e.open = true')
    page.locator('[data-tab=planning]').click()
    page.locator('#plan-subject').fill('검증용 쿠키')
    page.locator('#plan-question').fill('두께가 다르면 식감도 다를까?')
    page.locator('#plan-locked-script').locator('..').locator('..').locator('summary').click()
    original = '몇일 먹어봤는데 안 달아요.\n여러분은 먹어보셨나요?'
    page.locator('#plan-locked-script').fill(original)
    page.locator('#plan-build').click()
    page.wait_for_selector('#plan-merged-script')
    assert page.locator('#plan-merged-script').input_value() == original
    page.locator('#plan-review').click()
    page.wait_for_selector('[data-plan-fix]')
    page.locator('[data-plan-fix]').filter(has_text='며칠').first.click()
    page.wait_for_function("() => document.querySelector('#plan-merged-script').value.startsWith('며칠')")
    assert page.locator('#plan-merged-script').input_value() == original.replace('몇일', '며칠')
    assert page.locator('[data-plan-path="scenes.0.caption"]').input_value().startswith('며칠')
    option = page.locator('[data-plan-path="scenes.0.asset_id"] option').nth(1).get_attribute('value')
    for i in range(2):
        with page.expect_response(lambda r: '/api/projects/' in r.url and r.request.method == 'PUT'):
            page.locator(f'[data-plan-path="scenes.{i}.asset_id"]').select_option(option)
        if float(page.locator(f'[data-plan-path="scenes.{i}.source_start"]').input_value()) != i:
            with page.expect_response(lambda r: '/api/projects/' in r.url and r.request.method == 'PUT'):
                page.locator(f'[data-plan-path="scenes.{i}.source_start"]').fill(str(i))
                page.locator(f'[data-plan-path="scenes.{i}.source_start"]').press('Tab')
        with page.expect_response(lambda r: '/api/projects/' in r.url and r.request.method == 'PUT'):
            page.locator(f'[data-plan-path="scenes.{i}.source_end"]').fill(str(i + .5))
            page.locator(f'[data-plan-path="scenes.{i}.source_end"]').press('Tab')
    page.locator('#plan-apply').click()
    page.wait_for_function("() => document.querySelectorAll('[data-clip]').length === 2 && document.querySelector('#total-time').textContent === '00:01'")
    assert page.locator('#plan-content').inner_text().find('실제 연결 길이 1.00초') >= 0
    with page.expect_download() as plan_download:
        page.locator('#plan-download').click()
    plan_text = Path(plan_download.value.path()).read_text(encoding='utf-8')
    assert '며칠 먹어봤는데 안 달아요.' in plan_text and '몇일' not in plan_text
    page.locator('#undo').click()
    page.wait_for_function("() => document.querySelector('#total-time').textContent === '00:08'")
    page.locator('#redo').click()
    page.wait_for_function("() => document.querySelector('#total-time').textContent === '00:01'")
    page.locator('[data-tab=captions]').click()
    page.locator('#add-caption').click()
    page.wait_for_selector('[data-caption-text]')
    page.locator('[data-caption-text]').fill('🍫 초고파이는 안 달아요 · 1,500원')
    with page.expect_response(lambda r: '/api/projects/' in r.url and r.request.method == 'PUT'):
        page.locator('[data-caption-text]').press('Tab')
    page.locator('#corrections').fill('초고파이 => 초코파이')
    with page.expect_response(lambda r: '/api/projects/' in r.url and r.request.method == 'PUT'):
        page.locator('#save-corrections').click()
    page.wait_for_function("() => document.querySelector('#save-status').textContent.includes('저장됨')")
    page.locator('[data-caption-inspect]').click()
    page.wait_for_selector('[data-caption-suggestion]')
    assert '초고파이' in page.locator('[data-caption-text]').input_value()
    page.locator('[data-caption-suggestion]').click()
    page.wait_for_function("() => document.querySelector('[data-caption-text]').value.startsWith('🍫 초코파이')")
    page.locator('[data-tab=export]').click()
    with page.expect_response(lambda r: '/render' in r.url) as blocked:
        page.locator('#export').click()
    assert blocked.value.status == 422
    page.locator('[data-tab=captions]').click()
    page.locator('[data-caption-approve]').click()
    page.wait_for_selector('.caption-card.approved')
    with page.expect_download() as download:
        page.locator('#srt-download').click()
    content = Path(download.value.path()).read_text(encoding='utf-8')
    assert '🍫 초코파이는 안 달아요 · 1,500원' in content and '초고파이' not in content
    page.locator('[data-tab=export]').click()
    page.locator('#export').click()
    page.wait_for_function("() => [...document.querySelectorAll('.job b')].some(e => e.textContent.includes('영상 내보내기 · 완료'))", timeout=60000)
    page.locator('#plan-output').scroll_into_view_if_needed()
    page.screenshot(path=str(DATA / 'planning-desktop.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(DATA / 'planning-mobile.png'), full_page=True)
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    assert not errors, errors
    print('Planning browser: finalized script preservation, explicit typo suggestion, source mapping, undo/redo, caption dictionary, review gate, corrected SRT and actual MP4/ZIP passed.')
    print('Mobile 390px: no horizontal overflow; JavaScript page errors: 0. Synthetic test footage only.')
    browser.close()
