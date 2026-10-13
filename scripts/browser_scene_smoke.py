"""Actual footage smoke; provide STUDIO_SCENE_TEST_VIDEO and a matching silent scene query."""
import os,uuid,json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(os.environ['STUDIO_DATA_DIR']);errors=[]
source=os.environ['STUDIO_SCENE_TEST_VIDEO'];query=os.environ.get('STUDIO_SCENE_TEST_SCRIPT','빵을 자르는 단면 장면')
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
 page.goto(os.environ['STUDIO_TEST_URL']);page.locator('#password').fill((root/'owner-password').read_text().strip());page.locator('#login-form button').click();page.wait_for_function("() => !document.querySelector('#login-dialog').open")
 page.once('dialog',lambda d:d.accept('실제 무음 장면 검증 '+uuid.uuid4().hex[:6]));page.locator('#new-project').click();page.wait_for_timeout(500)
 page.locator('#edit-script').fill(query);page.locator('#edit-directions').fill('9:16')
 page.locator('#upload').set_input_files(source);page.wait_for_function("()=>!document.querySelector('#script-start').disabled",timeout=30000)
 page.locator('#script-start').click();page.wait_for_selector('[data-scene-select]',timeout=150000)
 assert '대사 없음 · 장면 후보 있음' in page.locator('#script-report').inner_text()
 page.wait_for_timeout(2000) # Polling must preserve expanded review panels.
 page.locator('[data-scene-preview]').first.click();page.wait_for_function("()=>document.querySelector('#player').currentTime>0")
 page.locator('[data-scene-select][data-scene-aux=false]').first.click();page.wait_for_function("()=>document.querySelector('#script-status').textContent.includes('대본 편집 완료')")
 assert not page.locator('#final-download').is_disabled()
 with page.expect_download(timeout=120000) as downloaded:page.locator('#final-download').click()
 file=Path(downloaded.value.path());assert file.stat().st_size>1000;print('Real silent source → scene intent/retrieval → original playback → manual selection → final MP4 button download:',file.stat().st_size)
 page.screenshot(path=str(root/'scene-search-browser.png'),full_page=True)
 assert not errors,errors;browser.close()
