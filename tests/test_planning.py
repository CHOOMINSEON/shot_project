import copy

import pytest

from studio import planning as p, proofreading as r, timeline as t
from test_app import upload_video, wait_job


@pytest.mark.parametrize('kind,expected', [('single', 18), ('comparison', 60), ('list', 60), ('cooking', 30)])
def test_missing_facts_and_taste_are_not_invented(kind, expected):
    plan = p.build(p.Brief(subject='신제품 쿠키', kind=kind))
    assert plan['target_seconds'] == expected
    assert '[실제 맛 반응]' in plan['script'] and '[시식 후 결정]' in plan['script']
    assert plan['script'] == p.script_from_scenes(plan)
    assert len(plan['summary']) <= 6
    assert len({h['angle'] for h in plan['hooks']}) == 3
    assert len(plan['titles']) == 5 and len(plan['thumbnails']) == 3
    assert all(s['total'] == sum(c['points'] for c in s['criteria']) for s in plan['scores'])
    assert all(s['provisional'] for s in plan['scores'])
    assert all(0 <= c['points'] <= 2 for s in plan['scores'] for c in s['criteria'])
    assert all(not ('최고' in title or '1위' in title) for title in plan['titles'])
    assert all(f'## {i})' in p.markdown(plan) for i in range(1, 7))


def test_final_script_preserved_and_typos_are_suggestions():
    script = '가격은 1,500원이고,\n몇일 먹어봤는데 안 달아요.\n여러분은 먹어보셨나요?\n'
    plan = p.build(p.Brief(subject='쿠키', locked_script=script, target_seconds=20))
    assert plan['script'] == script == p.script_from_scenes(plan)
    review = p.audit(plan)
    assert any(s['after'] == '며칠' for f in review['fields'] for s in f['suggestions'])
    assert '몇일' in plan['script']
    assert plan['target_seconds'] == 20


def test_assumptions_and_external_urls_are_not_verified_claims():
    plan = p.build(p.Brief(subject='쿠키', facts=[
        p.Fact(kind='가격', text='999원', source='assumption'),
        p.Fact(kind='출시일', text='2026-10-01', source='external', url='https://example.com')]))
    assert '999원' not in plan['script']
    assert '2026-10-01' not in plan['script']
    assert plan['facts'][1]['status'].startswith('확인 필요')
    assert any('출처' in reason for reason in p.audit(plan)['checks'])
    with pytest.raises(ValueError):
        p.Fact(text='x', url='javascript:alert(1)')


def test_dictionary_and_sensitive_words_not_autocorrected():
    text = '안 달아요. 몇일 먹었는데 10점 만점에 8점, 초고파이예요.'
    result = r.inspect_text(text, '초고파이 => 초코파이')
    assert {x['after'] for x in result['suggestions']} == {'며칠', '초코파이'}
    assert any('부정' in reason for reason in result['reasons'])
    assert any('숫자' in reason for reason in result['reasons'])
    assert '몇일' in text and '초고파이' in text


def test_review_receipt_invalidated_by_content_timing_or_source():
    item = {'text': '안 달아요', 'start': 0, 'end': 1, 'source_text': '안 달아요'}
    item['review_token'] = r.caption_token(item)
    assert r.approved(item)
    for key, value in [('text', '달아요'), ('start', .1), ('source_text', '못 달아요')]:
        changed = {**item, key: value}
        assert not r.approved(changed)
        with pytest.raises(ValueError, match='검수'):
            r.require_review([changed])


def test_regrouped_manual_corrections_are_archived_and_exact_source_edits_survive():
    state = {'clips': [{'id': 'old', 'asset_id': 'a', 'start': 0, 'end': 4}]}
    assets = {'a': {'analysis': {'words': [
        {'id': 'w1', 'start': 0, 'end': 1, 'text': '초고파이', 'confidence': .9},
        {'id': 'w2', 'start': 1, 'end': 2, 'text': ' 맛있어요', 'confidence': .9}]}}}
    state['captions'] = t.generate_captions(state, assets, 30)
    cap = state['captions']['items'][0]
    cap.update(text='초코파이 맛있어요', edited=True)
    state['clips'][0]['id'] = 'new-cut-id'
    result = t.generate_captions(state, assets, 30)
    assert result['items'][0]['text'] == '초코파이 맛있어요'
    state['clips'][0]['start'] = 1
    result = t.generate_captions(state, assets, 10)
    assert result['archived_edits'][0]['text'] == '초코파이 맛있어요'


def test_connected_storyboard_uses_real_duration_and_preserves_original(owner, sample):
    project, ident = upload_video(owner, sample)
    endpoint = '/api/projects/' + project['id']
    response = owner.post(endpoint + '/planning', json={'revision': project['revision'], 'brief': {
        'subject': '쿠키', 'target_seconds': 18, 'question': '이 두께면 씹는 느낌이 다를까?',
        'taste': '겉은 바삭하고 속은 부드러웠습니다.', 'conclusion': '내 기준에는 맞았습니다.',
        'criteria': '겉과 속의 식감 차이', 'motive': '두께를 비교하고 싶어서'}})
    assert response.status_code == 200, response.text
    project = response.json()
    assert owner.post(endpoint + '/planning/apply', json={'revision': project['revision']}).status_code == 422
    state = copy.deepcopy(project['state'])
    for i, scene in enumerate(state['planning']['scenes']):
        scene.update(asset_id=ident, source_start=i, source_end=i + .5)
    saved = owner.put(endpoint, json={'revision': project['revision'], 'name': project['name'], 'state': state}).json()
    applied = owner.post(endpoint + '/planning/apply', json={'revision': saved['revision']}).json()
    assert applied['duration'] == 2.5
    assert applied['state']['planning']['actual_seconds'] == 2.5
    assert applied['state']['planning']['target_seconds'] == 18
    assert not applied['state']['captions']['items']  # Planned speech is not inserted as a fake transcript.
    assert applied['assets'][0]['metadata']['duration'] == 8
    assert owner.get('/api/assets/' + ident + '/video').status_code == 200
    markdown = owner.get(endpoint + '/planning.md').text
    assert '겉은 바삭하고 속은 부드러웠습니다.' in markdown
    job = owner.post(endpoint + '/render', json={'revision': applied['revision'], 'preview': True}).json()
    result = wait_job(owner, job['job_id'])
    assert result['status'] == 'completed', result['message']


def test_review_gate_and_reconfirmation_after_edit(owner, sample):
    project, ident = upload_video(owner, sample)
    endpoint = '/api/projects/' + project['id']
    state = project['state']
    state['captions'] = {'signature': t.signature(state), 'items': [
        {'id': 'c', 'text': '안 달아요 · 1,500원', 'start': 0, 'end': 2}]}
    project = owner.put(endpoint, json={'revision': project['revision'], 'name': project['name'], 'state': state}).json()
    assert owner.post(endpoint + '/render', json={'revision': project['revision']}).status_code == 422
    project = owner.post(endpoint + '/captions/review', json={'revision': project['revision'], 'caption_ids': ['c']}).json()
    assert project['state']['captions']['items'][0]['reviewed']
    assert owner.get(endpoint + '/captions.srt').status_code == 200
    project['state']['captions']['items'][0]['text'] = '달아요 · 1,500원'
    project = owner.put(endpoint, json={'revision': project['revision'], 'name': project['name'], 'state': project['state']}).json()
    assert not project['state']['captions']['items'][0]['reviewed']
    assert owner.get(endpoint + '/captions.srt').status_code == 422
    project['state']['captions']['items'][0]['text'] = '[실제 맛 반응]'
    project = owner.put(endpoint, json={'revision': project['revision'], 'name': project['name'], 'state': project['state']}).json()
    assert owner.post(endpoint + '/captions/review', json={'revision': project['revision'], 'caption_ids': ['c']}).status_code == 422


def test_upload_refuses_insufficient_disk(owner, monkeypatch):
    from collections import namedtuple
    from studio import app as app_module
    usage = namedtuple('Usage', 'total used free')
    monkeypatch.setattr(app_module.shutil, 'disk_usage', lambda _: usage(100, 99, 1))
    project = owner.post('/api/projects', json={'name': '공간 부족'}).json()
    assert owner.post('/api/projects/' + project['id'] + '/uploads', json={'name': 'x.mp4', 'size': 1}).status_code == 507


def test_resumed_transcript_keeps_original_model_identity(owner, sample, monkeypatch):
    from studio import worker
    from studio.settings import DATA
    project, ident = upload_video(owner, sample)
    work = DATA / 'work' / 'checkpoint-model-test'
    work.mkdir()
    # Final window saved before the DB commit; legacy checkpoints were created with base.
    worker.atomic_json(work / 'analysis.json', {'next': 120, 'speech': [[0, 2]], 'peaks': [],
                       'words': [{'id': 'w0', 'start': 0, 'end': 1, 'text': '안 달아요'}]})
    loaded = []
    def load(name=None):
        loaded.append(name)
        return object()
    monkeypatch.setattr(worker, 'load_model', load)
    worker.analyze('checkpoint-model-test', {'asset_id': ident, 'transcribe': True, 'model': 'medium'})
    analysis = owner.get('/api/projects/' + project['id']).json()['assets'][0]['analysis']
    assert loaded == ['base']
    assert analysis['model'] == 'base'
    assert analysis['words'][0]['text'] == '안 달아요'
