"""Run against a local server with Playwright + Chromium installed. Creates a test project."""
import json
import os
import sys
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio.settings import DATA

errors = []
project_name = '브라우저 검증 리뷰 ' + uuid.uuid4().hex[:6]
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
    page.locator('#clip-end').fill('4')
    page.locator('#clip-save').click()
    page.wait_for_function("() => document.querySelector('#total-time').textContent === '00:04'")
    page.locator('[data-tab=captions]').click()
    page.locator('#add-caption').click()
    page.wait_for_selector('[data-caption-text]')
    page.locator('[data-caption-text]').fill('안 달아요 · 10점 만점에 8점')
    with page.expect_response(lambda response: '/api/projects/' in response.url and response.request.method == 'PUT') as saved:
        page.locator('[data-caption-text]').press('Tab')
    assert saved.value.status == 200
    page.locator('[data-caption-inspect]').click()
    page.wait_for_selector('.review-findings')
    page.locator('[data-caption-approve]').click()
    page.wait_for_function("() => document.querySelector('.caption-card').classList.contains('approved')")
    page.locator('[data-tab=export]').click()
    page.locator('#export').click()
    page.wait_for_function("() => [...document.querySelectorAll('.job b')].some(e => e.textContent.includes('영상 내보내기 · 완료'))", timeout=60000)
    page.screenshot(path=str(DATA / 'studio-desktop.png'), full_page=True)
    assert page.locator('#jobs a').count() == 4
    page.set_viewport_size({'width': 390, 'height': 844})
    page.screenshot(path=str(DATA / 'studio-mobile.png'), full_page=True)
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    assert not errors, errors
    print('Browser: login, project creation, upload, boundary edit, Korean caption edit, MP4/SRT/ZIP export passed.')
    print('Mobile layout: no horizontal overflow. JavaScript page errors: 0.')
    browser.close()
