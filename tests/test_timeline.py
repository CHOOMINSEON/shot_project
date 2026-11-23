import pytest

from studio import timeline as t
from studio.settings import MAX_FILE_BYTES, MAX_INPUT_SECONDS, MAX_OUTPUT_SECONDS


def state():
    return {'clips': [{'id': 'a', 'asset_id': 'src', 'start': 0, 'end': 5, 'label': '첫 제품'},
                      {'id': 'b', 'asset_id': 'src', 'start': 10, 'end': 15, 'label': '둘째 제품'}],
            'protections': [], 'captions': {'items': []}}


def assets():
    return {'src': {'analysis': {'words': [{'id': 'w1', 'start': 1, 'end': 2, 'text': '안 달아요', 'review': False},
                                          {'id': 'w2', 'start': 11, 'end': 12, 'text': '10점 만점에 8점', 'review': False}]}}}


def test_input_and_output_limits_are_distinct():
    assert (MAX_FILE_BYTES, MAX_INPUT_SECONDS, MAX_OUTPUT_SECONDS) == (10_000_000_000, 7200, 1800)


def test_protection_survives_repeated_cut():
    s = state()
    s['protections'] = [{'asset_id': 'src', 'start': 2, 'end': 3}]
    for _ in range(2):
        t.apply_cuts(s, 'src', [{'start': 1, 'end': 4}])
    assert [[c['start'], c['end']] for c in s['clips'][:3]] == [[0, 1], [2, 3], [4, 5]]
    assert s['protections'][0]['start'] == 2


def test_vad_candidates_keep_speech_margins():
    assert t.cut_candidates([[0, 1], [2, 3]], 3) == [{'start': 1.2, 'end': 1.88}]


def test_individual_cut_restore_does_not_duplicate_kept_content():
    s = state()
    s['protections'] = [{'asset_id': 'src', 'start': 2, 'end': 3}]
    t.apply_cuts(s, 'src', [{'start': 1, 'end': 4}])
    t.restore_cuts(s, 'src', [{'start': 1, 'end': 4}])
    assert t.duration(s['clips']) == 10


def test_gap_restore_preserves_earlier_manual_trim():
    s = state()
    t.apply_cuts(s, 'src', [{'start': 0, 'end': 8}])
    t.restore_cuts(s, 'src', [{'start': 0, 'end': 8}])
    assert t.duration(s['clips']) == 10
    assert all(c['end'] <= 5 or c['start'] >= 10 for c in s['clips'])
    t.restore_cuts(s, 'src', [{'start': 1, 'end': 4}])
    assert t.duration(s['clips']) == 10


def test_reorder_duplicate_and_text_edits_sync():
    s = state()
    caps = t.generate_captions(s, assets(), 30)
    assert [c['start'] for c in caps['items']] == [1, 6]
    caps['items'][0]['text'] = '안 달아요!'
    caps['items'][0]['edited'] = True
    s['captions'] = caps
    first, second = s['clips']
    s['clips'] = [second, first, {**first, 'id': 'duplicate'}]
    result = t.generate_captions(s, assets(), 30)
    assert [c['start'] for c in result['items']] == [1, 6, 11]
    # A duplicate of the same source words inherits the verified spelling edit too.
    assert [c['text'] for c in result['items']] == ['10점 만점에 8점', '안 달아요!', '안 달아요!']
    assert result['signature'] != caps['signature']


def test_cut_boundary_marks_caption_for_review():
    s = state()
    s['clips'][0]['start'] = 1.5
    item = t.generate_captions(s, assets())['items'][0]
    assert item['start'] == 0
    assert item['review']


def test_srt_local_timing_and_korean():
    caps = [{'start': 5.5, 'end': 7, 'text': '안 달아요\n가격은 1,500원'}]
    content = t.srt(t.local_captions(caps, 5, 8), 3)
    assert content == '1\n00:00:00,500 --> 00:00:02,000\n안 달아요\n가격은 1,500원\n\n'


@pytest.mark.parametrize('items', [[{'start': -1, 'end': 1, 'text': 'x'}],
                                  [{'start': 1, 'end': 1, 'text': 'x'}],
                                  [{'start': 1, 'end': 4, 'text': 'x'}],
                                  [{'start': 0, 'end': 2, 'text': 'x'}, {'start': 1, 'end': 3, 'text': 'y'}]])
def test_invalid_caption_ranges_fail(items):
    with pytest.raises(ValueError):
        t.srt(items, 3)


def test_output_length_limit_does_not_delete_content():
    s = state()
    s['clips'] = [{**s['clips'][0], 'end': 1800}]
    assert len(t.export_groups(s, 'full')) == 1
    s['clips'].append({**s['clips'][0], 'id': 'other', 'label': '다른 제품', 'end': 1})
    with pytest.raises(ValueError, match='자동으로 잘라내지'):
        t.export_groups(s, 'full')
    assert t.duration(s['clips']) == 1801
    assert len(t.export_groups(s, 'products')) == 2


def test_no_product_is_automatically_confirmed():
    candidates = t.product_candidates([{'start': 0, 'text': '다음은 신상 제품'}], [], 8)
    assert candidates[0]['review']


def _caption_asset(words, speech, duration=30.):
    return {'id': 'a', 'name': 'a.mp4', 'metadata': {'duration': duration},
            'analysis': {'words': words, 'speech': speech}}


def test_captions_follow_real_voice_when_asr_is_late():
    from studio import timeline
    # 인식기는 1.0초에 말을 시작했다고 찍었지만 실제 목소리(VAD)는 0.4초부터
    words = [{'id': 'w0', 'start': 1.0, 'end': 1.6, 'text': ' 먼저', 'confidence': .9},
             {'id': 'w1', 'start': 1.6, 'end': 2.6, 'text': ' 소금우유는', 'confidence': .9}]
    asset = _caption_asset(words, [[.4, 2.2]])
    state = {'clips': [{'id': 'c1', 'asset_id': 'a', 'start': .25, 'end': 2.4}], 'captions': {'items': []}}
    items = timeline.generate_captions(state, {'a': asset})['items']
    assert len(items) == 1 and items[0]['text'] == '먼저 소금우유는'
    assert abs(items[0]['start'] - .15) < .05      # 0.4 - 0.25 (컷 시작)
    assert items[0]['end'] <= 2.2 - .25 + .01


def test_montage_pieces_do_not_repeat_the_same_word():
    from studio import timeline
    words = [{'id': 'w0', 'start': 10., 'end': 11.2, 'text': ' 먼저', 'confidence': .9},
             {'id': 'w1', 'start': 11.2, 'end': 12., 'text': ' 소금우유는', 'confidence': .9}]
    asset = _caption_asset(words, [[10., 12.]])
    clips = [{'id': f'c{i}', 'asset_id': 'a', 'start': 10 + i * .3, 'end': 10.3 + i * .3} for i in range(4)]
    clips.append({'id': 'c4', 'asset_id': 'a', 'start': 11.2, 'end': 12.})
    items = timeline.generate_captions({'clips': clips, 'captions': {'items': []}}, {'a': asset})['items']
    text = ' '.join(i['text'] for i in items)
    assert text.count('먼저') == 1 and text.count('소금우유는') == 1


def test_words_land_outside_removed_pause():
    from studio import timeline
    # 한 단어가 1.5초 쉼을 덮을 만큼 길게 찍혔다. 쉼을 뺀 두 컷에 같은 자막이 두 번 나오면 안 된다.
    words = [{'id': 'w0', 'start': 5., 'end': 8.5, 'text': ' 필링까지', 'confidence': .9},
             {'id': 'w1', 'start': 8.5, 'end': 9.5, 'text': ' 들어갔다는데', 'confidence': .9}]
    asset = _caption_asset(words, [[5., 6.], [7.5, 9.5]])
    clips = [{'id': 'c1', 'asset_id': 'a', 'start': 4.9, 'end': 6.15}, {'id': 'c2', 'asset_id': 'a', 'start': 7.35, 'end': 9.6}]
    items = timeline.generate_captions({'clips': clips, 'captions': {'items': []}}, {'a': asset})['items']
    text = ' '.join(i['text'] for i in items)
    assert text.count('필링까지') == 1 and text.count('들어갔다는데') == 1


def test_captions_without_vad_keep_asr_times():
    from studio import timeline
    words = [{'id': 'w0', 'start': 1., 'end': 1.5, 'text': ' 안녕', 'confidence': .9}]
    asset = _caption_asset(words, [])
    items = timeline.generate_captions({'clips': [{'id': 'c', 'asset_id': 'a', 'start': 0, 'end': 3}], 'captions': {'items': []}}, {'a': asset})['items']
    assert items[0]['start'] == 1. and items[0]['end'] >= 1.5


def test_transcript_vocabulary_and_retranscribe_rules():
    from studio import worker
    state = {'vocabulary': 'CU 소금우유, 크림브륄레\n크림브륄레', 'scene_products': [{'name': '호지차', 'brand': 'GS25', 'variant': ''}]}
    vocab = worker.transcript_vocabulary(state)
    assert vocab == 'CU 소금우유, 크림브륄레, 호지차 GS25'
    done = {'analysis': {'transcribed': True, 'model': 'medium', 'vocabulary': vocab}}
    assert worker.needs_transcript(done, 'large-v3', vocab)             # 더 정확한 모델이 생겼다
    assert not worker.needs_transcript(done, 'medium', vocab)           # 같은 모델·같은 단어장
    assert worker.needs_transcript(done, 'medium', vocab + ', 신상')     # 단어장이 바뀌었다
    assert not worker.needs_transcript(done, 'large-v3', vocab, ready=False)  # 모델 준비 전엔 기존 인식 사용
    assert worker.needs_transcript({'analysis': {}}, 'medium', '', ready=False)


def test_real_1122_project_captions_have_each_word_once_and_old_captions_are_rebuilt():
    # 사용자 PC의 '1122 가나 프리미엄' 실제 값: 0.27초 몽타주 컷 4개 + 쉼을 뺀 컷들, 8.3초로 늘어진 '필링까지'.
    # 이전 버전이 저장한 자막은 '먼저'가 4번, '필링까지'가 3번이었다(사용자: '먼저를 무슨 4번이나').
    from studio import timeline
    words = [{'id': 'w2', 'start': 120.94, 'end': 122.58, 'text': ' 먼저', 'confidence': .69},
             {'id': 'w3', 'start': 122.58, 'end': 122.90, 'text': ' 수유', 'confidence': .65},
             {'id': 'w4', 'start': 122.90, 'end': 124.62, 'text': ' 소금우유는', 'confidence': .81},
             {'id': 'w5', 'start': 126.63, 'end': 127.51, 'text': ' 밀크초콜릿에', 'confidence': .81},
             {'id': 'w6', 'start': 129.11, 'end': 131.61, 'text': ' 소금우유', 'confidence': .91},
             {'id': 'w7', 'start': 133.24, 'end': 141.58, 'text': ' 필링까지', 'confidence': .85},
             {'id': 'w8', 'start': 141.58, 'end': 143.0, 'text': ' 캐러멜칩이', 'confidence': .9},
             {'id': 'w9', 'start': 143.0, 'end': 144.4, 'text': ' 들어갔다는데', 'confidence': .9}]
    speech = [[121.336, 122.008], [122.232, 123.832], [126.648, 127.96], [130.36, 132.408], [134.84, 135.032],
              [135.352, 136.632], [138.4, 139.7], [140.3, 141.6], [142.7, 144.4]]
    asset = _caption_asset(words, speech)
    cuts = [(121.2, 121.467), (121.467, 121.733), (121.733, 122.0), (122.0, 122.267), (122.267, 123.133), (123.133, 124.033),
            (126.467, 128.167), (134.667, 136.833), (138.3, 139.867), (140.167, 141.767), (142.667, 144.533)]
    clips = [{'id': f'c{i}', 'asset_id': 'a', 'start': a, 'end': b} for i, (a, b) in enumerate(cuts)]
    old = [{'id': f'old{i}', 'start': i * .27, 'end': i * .27 + .26, 'text': '먼저', 'source_key': 'a:w2:w2', 'edited': False} for i in range(4)]
    state = {'clips': clips, 'captions': {'items': old, 'signature': timeline.signature({'clips': clips})}}
    assert timeline.stale_captions(state)
    caps = timeline.sync_captions(state, state, {'a': asset})
    assert not timeline.stale_captions({'captions': caps})
    texts = [c['text'] for c in caps['items']]
    joined = ' '.join(texts)
    for word in ('먼저', '소금우유는', '밀크초콜릿에', '필링까지', '캐러멜칩이', '들어갔다는데'):
        assert joined.count(word) == 1, texts
    assert all(a['end'] <= b['start'] + 1e-6 for a, b in zip(caps['items'], caps['items'][1:]))   # 겹치는 자막 없음
    assert all(a != b for a, b in zip(texts, texts[1:]))


def test_recognizer_repeating_a_word_on_top_of_itself_shows_once():
    from studio import timeline
    words = [{'id': f'w{i}', 'start': 1. + i * .05, 'end': 1.4 + i * .05, 'text': ' 먼저', 'confidence': .5} for i in range(3)] + \
            [{'id': 'w9', 'start': 1.6, 'end': 2.2, 'text': ' 소금우유는', 'confidence': .9}]
    asset = _caption_asset(words, [])
    items = timeline.generate_captions({'clips': [{'id': 'c', 'asset_id': 'a', 'start': 0, 'end': 3}], 'captions': {'items': []}}, {'a': asset})['items']
    assert ' '.join(i['text'] for i in items).count('먼저') == 1, items


def test_sentence_with_a_swallowed_repeat_gets_a_caption_on_every_voiced_piece():
    # 1122 원본 133~145초: '필링까지'가 8초짜리 한 단어로 찍혔다. 편집에 남는 목소리 138.4·140.3·142.8초에
    # 필링까지 / 캐러멜칩이 / 들어갔다는데가 하나씩 나와야 한다(사용자 캡처 0:14: 말하는데 자막이 없었다).
    asset = {'id': 'a', 'metadata': {'duration': 160, 'has_video': True}, 'analysis': {
        'words': [{'id': 'a', 'text': ' 필링까지', 'start': 133.24, 'end': 141.58},
                  {'id': 'b', 'text': ' 캐러멜칩이', 'start': 141.58, 'end': 143.46},
                  {'id': 'c', 'text': ' 들어갔다는데.', 'start': 143.46, 'end': 144.78}],
        'speech': [[134.84, 135.03], [135.35, 136.63], [138.42, 139.67], [140.31, 141.56], [142.81, 144.31]]}}
    placed = {w['text'].strip(' .'): (w['start'], w['end']) for w in t.voice_words(asset)}
    assert 138.42 <= placed['필링까지'][0] < 139.67
    assert 140.31 <= placed['캐러멜칩이'][0] < 141.56
    assert 142.81 <= placed['들어갔다는데'][0] < 144.31
