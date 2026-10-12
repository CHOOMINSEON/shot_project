"""Exercise the one-click workflow against a disposable local server."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

errors = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(os.environ['STUDIO_TEST_URL'])
    page.locator('#password').fill((Path(os.environ['STUDIO_DATA_DIR']) / 'owner-password').read_text().strip())
    page.locator('#login-form button').click()
    page.wait_for_function("() => !document.querySelector('#login-dialog').open")
    assert page.locator('#auto-cut').is_disabled()
    # Upload automatically creates a project; no modal or project setup required.
    page.locator('#upload').set_input_files('/tmp/iyoring-sample.mp4')
    page.wait_for_function("() => !document.querySelector('#auto-cut').disabled", timeout=30000)
    assert page.locator('#analyze').is_disabled()  # No Whisper model in this disposable server.
    page.locator('#auto-cut').click()
    page.wait_for_function("() => document.querySelector('#quick-status').textContent.includes('자동 편집 완료')", timeout=60000)
    assert '삭제' in page.locator('#quick-status').inner_text()
    assert page.locator('[data-clip]').count() == 2
    page.wait_for_function("() => document.querySelector('#player').src.includes('/api/exports/')")
    assert page.locator('#quick-play').is_visible() and page.locator('#auto-undo').is_visible()
    page.locator('#quick-export').click()
    page.wait_for_selector('#quick-downloads a', timeout=60000)
    with page.expect_download() as download:
        page.locator('#quick-downloads a').first.click()
    result = download.value
    assert result.suggested_filename.endswith('.mp4') and Path(result.path()).stat().st_size > 1000
    page.screenshot(path=str(Path(os.environ['STUDIO_DATA_DIR']) / 'automatic-cut-desktop.png'), full_page=True)
    page.locator('#auto-undo').click()
    page.wait_for_function("() => document.querySelector('#total-time').textContent === '00:08'")
    assert page.locator('[data-clip]').count() == 1
    assert page.locator('#auto-undo').is_hidden()
    page.set_viewport_size({'width': 390, 'height': 844})
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    page.screenshot(path=str(Path(os.environ['STUDIO_DATA_DIR']) / 'automatic-cut-mobile.png'), full_page=True)
    assert not errors, errors
    print('Browser: automatic project, upload, model-free automatic silence cut, real preview playback, full MP4 download, mobile layout passed; JavaScript errors: 0.')
    browser.close()
