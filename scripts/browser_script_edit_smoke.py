"""Real Korean recording: ASR -> script alignment -> preview -> final MP4, plus dubbing."""
import os
import uuid
from pathlib import Path
from playwright.sync_api import sync_playwright

errors=[]
data=Path(os.environ['STUDIO_DATA_DIR'])
reference=Path('/tmp/iyoring-korean-groundtruth.txt').read_text().strip()
with sync_playwright() as playwright:
    browser=playwright.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(os.environ['STUDIO_TEST_URL'])
    page.locator('#password').fill((data/'owner-password').read_text().strip())
    page.locator('#login-form button').click()
    page.wait_for_function("() => !document.querySelector('#login-dialog').open")
    if page.locator('[data-asset]').count():
        name='대본 자동 편집 검증 '+uuid.uuid4().hex[:6]
        page.once('dialog',lambda dialog:dialog.accept(name))
        page.locator('#new-project').click()
        page.wait_for_function('(name) => document.querySelector("#workspace-name").textContent===name',arg=name)
    assert not page.locator('#advanced-edit').get_attribute('open')
    page.locator('#edit-script').fill(reference)
    page.locator('#edit-directions').fill('9:16, 첫 문장 클로즈업, 빠른 템포')
    page.locator('#upload').set_input_files('/tmp/iyoring-korean-sample.mp4')
    page.wait_for_function("() => !document.querySelector('#script-start').disabled",timeout=30000)
    assert page.locator('#edit-script').input_value()==reference  # Pre-upload draft survives automatic project creation.
    page.locator('#script-start').click()
    page.wait_for_function("() => document.querySelector('#script-status').textContent.includes('대본 편집 완료')",timeout=240000)
    assert '1/1줄 연결' in page.locator('#script-status').inner_text()
    assert not page.locator('#script-export').is_disabled()
    page.wait_for_function("() => document.querySelector('#player').src.includes('/api/exports/')")
    page.locator('#script-export').click()
    page.wait_for_selector('#script-downloads a',timeout=90000)
    with page.expect_download() as download:
        page.locator('#script-downloads a').first.click()
    assert Path(download.value.path()).stat().st_size>1000
    # Upload the same recording as a separate WAV. The new job must actually transcribe the dubbing.
    page.locator('#dubbing-upload').set_input_files('/tmp/iyoring-script-dubbing.wav')
    page.wait_for_function("() => document.querySelectorAll('[data-asset]').length === 2 && !document.querySelector('#script-start').disabled",timeout=30000)
    page.locator('#script-start').click()
    page.wait_for_function("() => document.querySelector('#script-status').textContent.includes('대본 편집 완료') && document.querySelector('#script-report').textContent.includes('화면:')",timeout=240000)
    assert not page.locator('#script-export').is_disabled()
    page.screenshot(path=str(data/'script-edit-desktop.png'),full_page=True)
    page.locator('#edit-script').fill(reference+'\n[실제 맛 평가]')
    page.locator('#script-start').click()
    page.wait_for_function("() => document.querySelector('#script-status').textContent.includes('부분 미리보기')",timeout=90000)
    assert page.locator('#script-export').is_disabled()
    assert '내용 미정' in page.locator('#script-report').inner_text()
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(data/'script-edit-mobile.png'),full_page=True)
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
    assert not errors,errors
    print('Real Korean browser: pre-upload script preservation, original ASR/script matching/directing, preview/final MP4 download, separate WAV ASR and dubbing, placeholders/partial preview gate, mobile layout passed. JS errors: 0.')
    browser.close()
