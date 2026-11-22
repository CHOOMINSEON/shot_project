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
