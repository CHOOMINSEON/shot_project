"""지침 기반 자동 편집 규칙 테스트(순수 Python, 합성 데이터).

주의: 합성 단어·프레임으로 로직을 검증한다. 실제 음성 인식/시각 모델 정확도 검증이 아니다.
"""
import os
import re
import tempfile
from pathlib import Path

os.environ.setdefault('STUDIO_DATA_DIR', tempfile.mkdtemp(prefix='guided-tests-'))

from studio import guided, timeline

DEFAULT = None


def default_guideline():
    return guided.DEFAULT_GUIDELINE_GENERAL


def w(ident, text, a, b, conf=.95):
    return {'id': f'w{ident}', 'text': text, 'start': a, 'end': b, 'confidence': conf}


def tokens(words):
    """Whisper는 단어마다 토큰을 준다. 구절 하나로 넣은 합성 데이터를 단어 단위로 펼쳐 시간을 균등 배분."""
    result = []
    for item in words:
        parts = item['text'].split()
        step = (item['end'] - item['start']) / max(1, len(parts))
        for k, part in enumerate(parts):
            result.append({**item, 'id': f"{item['id']}.{k}", 'text': (' ' if k == 0 or True else '') + part,
                           'start': item['start'] + k * step, 'end': item['start'] + (k + 1) * step})
    return result


def asset(words, duration=60, name='원본.mp4', ident='v', width=1080, height=1920):
    words = tokens(words)
    return {'id': ident, 'name': name, 'status': 'ready', 'analysis': {'words': words, 'transcribed': True},
            'metadata': {'duration': duration, 'has_video': True, 'has_audio': True, 'width': width, 'height': height, 'rotation': 0}}


def frame(i, start, end, tags, shot=0):
    return {'id': f'{int(start*1e6):012d}', 'start': start, 'end': end, 'shot': shot, 'tags': tags, 'ocr': [], 'scene_cut': False}


def review_words():
    return [
        w(1, ' 자 카메라 잠깐만.', 1, 3),                     # 준비/촬영 지시
        w(2, ' 오늘은 편의점 신상 크림빵을 먹어볼게요.', 8, 11),  # 소개
        w(3, ' 이거 식감이 쫄깃', 20, 21.5, .9),               # 말실수(미완성)
        w(4, ' 이거 식감이 쫄깃하고 촉촉해서 맛있어요.', 22, 25),  # 재시도
        w(5, ' 가격은 2500원이에요.', 30, 32),
        w(6, ' 가격은 2500원이에요.', 33, 35, .8),            # 같은 내용 반복
        w(7, ' 크림이 조금 아쉬워요.', 40, 42),
        w(8, ' 그래서 다시 사 먹고 싶어요.', 50, 52),
    ]


def run(words=None, frames=None, guideline=None, style='oneshot', duration=60, **kw):
    a = asset(words if words is not None else review_words(), duration, **kw)
    rules = guided.parse_guideline(guideline if guideline is not None else default_guideline(), style)
    return guided.plan([a], rules, {'v': frames or []}, {}), rules, a


def test_default_guideline_is_parsed_without_closeup_misread():
    rules = guided.parse_guideline(default_guideline(), 'oneshot')
    assert rules['target'] == (30, 90)
    assert rules['frame'] == 'auto'            # '제품 클로즈업'을 전체 크롭으로 오판하지 않음
    assert {'packaging', 'opening', 'crosssection', 'eating', 'conclusion'} <= rules['keep']
    assert {'prep', 'repeat', 'retake', 'silence'} <= rules['drop']
    assert rules['hook'] == 'speech'
    assert rules['order'][0] == 'intro' and rules['order'][-1] == 'conclusion'
    assert rules['group_products']


def test_style_adds_roles_and_unsupported_items_are_reported():
    rules = guided.parse_guideline('배경음악 넣고 효과음 추가, 30초', 'recipe')
    assert 'cooking' in rules['keep'] and rules['target'][1] == 30
    assert any('음악' in x for x in rules['unapplied']) and any('효과음' in x for x in rules['unapplied'])


def test_prep_retake_and_repeat_are_dropped_with_reasons():
    result, _, _ = run()
    texts = [u['text'] for u in result['units']]
    assert not any('카메라' in t for t in texts)
    # 말실수("이거 식감이 쫄깃")는 삭제되고, 완성된 재시도만 남는다 → 같은 말이 두 번 나오면 안 됨
    tasty = [t for t in texts if '촉촉' in t]
    assert len(tasty) == 1 and tasty[0].count('쫄깃') == 1
    codes = {r['reason_code'] for r in result['removed']}
    assert any(r['reason_code'] == 'retake' and '쫄깃' in r['text'] and '촉촉' not in r['text'] for r in result['removed'])
    spans = sorted((r['start'], r['end']) for r in result['removed'] if r['asset_id'] == 'v')
    assert all(b[0] >= a[1] - .001 for a, b in zip(spans, spans[1:]))   # 삭제 기록이 서로 겹치지 않음
    assert {'prep', 'retake', 'repeat'} <= codes
    prices = [t for t in texts if '2500' in t]
    assert len(prices) == 1                     # 반복 중 하나만


def test_conclusion_is_kept_and_not_invented_when_absent():
    result, _, _ = run()
    assert any('repurchase' in u['labels'] for u in result['units'])
    no_end = [x for x in review_words() if x['id'] != 'w8']
    result, _, _ = run(no_end)
    assert any('결론' in m for m in result['missing'])
    assert not any('repurchase' in u['labels'] or 'conclusion' in u['labels'] for u in result['units'])


def test_numbers_and_negation_prevent_false_repeat():
    words = [w(1, ' 이거 정말 맛있어요.', 5, 7), w(2, ' 이거 정말 맛없어요.', 9, 11), w(3, ' 가격은 2500원이에요.', 14, 16),
             w(4, ' 가격은 3500원이에요.', 18, 20)]
    result, _, _ = run(words, guideline='', duration=30)
    texts = [u['text'] for u in result['units']]
    assert len(texts) == 4                       # 숫자·부정이 다르면 반복으로 지우지 않음
    assert any(u['review'] for u in result['units'])


def test_silent_eating_and_cross_section_are_kept_but_idle_is_cut():
    frames = [frame(0, 12, 13, {'crosssection': .3}), frame(1, 13, 16, {'crosssection': .3}),
              frame(2, 16, 17, {'eating': .3}, shot=1), frame(3, 17, 19, {'eating': .3}, shot=1)]
    result, _, _ = run(frames=frames)
    roles = [u['role'] for u in result['units'] if u['kind'] == 'visual']
    assert 'crosssection' in roles and 'eating' in roles
    # 말 없는 단면·시식 컷은 단독으로 남거나, 맛 평가 소리 위에 화면으로 얹혀서 남는다
    assert any((c['start'] <= 13 and c['end'] >= 16) or (c.get('visual_asset_id') and 12 <= c['visual_start'] < 19) for c in result['clips'])
    # 4~7초 대기는 어떤 클립에도 포함되지 않음
    assert not any(c['start'] < 6 < c['end'] for c in result['clips'])


def test_food_present_alone_does_not_protect():
    frames = [frame(0, 12, 19, {'product_full': .3, 'closeup': .3, 'holding': .3})]
    result, _, _ = run(frames=frames)
    assert not [u for u in result['units'] if u['kind'] == 'visual']


def test_long_silent_visual_is_trimmed_and_recorded():
    frames = [frame(i, 12 + i, 13 + i, {'eating': .3}) for i in range(10)]
    result, _, _ = run(frames=frames)
    removed = [r for r in result['removed'] if r['reason_code'] == 'long_visual']
    assert removed


def test_length_trim_never_cuts_inside_a_sentence_or_drops_conclusion():
    words = []
    t = 1
    for i in range(50):
        words.append(w(i, f' 일반 이야기 {i}번째 문장이에요.', t, t + 2))
        t += 3
    words.append(w(99, ' 결론은 다시 사 먹고 싶어요.', t, t + 2))
    result, rules, a = run(words, duration=t + 5)
    assert result['seconds'] <= 90 * rules['playback']      # 목표는 배속 후 길이
    assert any('repurchase' in u['labels'] for u in result['units'])
    spans = [(x['speech_start'] if 'speech_start' in x else None) for x in result['units']]
    for clip in result['clips']:
        for unit in clip['guided']['units']:
            assert unit['end'] > unit['start']
    assert any(r['reason_code'] == 'length' for r in result['removed'])


def test_too_short_source_warns_instead_of_padding():
    result, _, _ = run()
    assert any('목표 최소' in x for x in result['warnings'])
    assert result['seconds'] < 45


def test_hook_moves_only_self_contained_question_or_evaluation():
    words = [w(1, ' 오늘은 편의점 신상 크림빵을 먹어볼게요.', 3, 6), w(2, ' 이거 정말 쫄깃하고 맛있어요.', 10, 12),
             w(3, ' 컵라면으로 파스타가 될까요?', 20, 23), w(4, ' 그래서 다시 사 먹고 싶어요.', 30, 32),
             w(5, ' 가격은 2500원이에요.', 40, 42)]
    result, _, _ = run(words, duration=50)
    assert result['units'][0]['text'].strip().startswith('컵라면으로')   # 단독으로 의미가 통하는 질문
    assert result['moved']
    words[2] = w(3, ' 그래서 컵라면으로 파스타가 될까요?', 20, 23)
    result, _, _ = run(words, duration=50)
    assert not result['moved']                                         # 접속어: 원래 맥락 유지


def test_negative_evaluation_is_not_moved_to_front():
    words = [w(1, ' 안녕하세요 오늘은 신상입니다.', 3, 6), w(2, ' 맛은 별로 안 달아요.', 10, 12),
             w(3, ' 가격은 2500원이에요.', 20, 22), w(4, ' 다시 사 먹을 것 같아요.', 30, 32)]
    result, _, _ = run(words, duration=40)
    assert not result['moved']


def test_no_analysis_keeps_whole_source_and_says_so():
    a = asset([], 20)
    rules = guided.parse_guideline('', 'oneshot')
    result = guided.plan([a], rules, {}, {})
    assert result['clips'][0]['end'] == 20 and result['warnings']


def test_frame_mode_auto_uses_blur_for_landscape_and_fit_for_portrait():
    result, _, _ = run(width=1920, height=1080)
    assert result['clips'][0]['frame']['mode'] == 'blur'
    result, _, _ = run(width=1080, height=1920)
    assert result['clips'][0]['frame']['mode'] == 'fit'


def test_product_continuity_is_marked_for_review_not_confirmed():
    frames = [frame(0, 12, 16, {'crosssection': .3})]
    evidence = {('v', frames[0]['id']): [{'name': '크림빵', 'status': 'continuity_candidate', 'reasons': ['같은 연속 숏'],
                                          'uncertainties': ['제품명 재노출 없음']}]}
    a = asset(review_words())
    rules = guided.parse_guideline(default_guideline(), 'oneshot')
    result = guided.plan([a], rules, {'v': frames}, evidence)
    unit = next(u for u in result['units'] if u['kind'] == 'visual')
    assert unit['product']['status'] == '확인 필요' and unit['status'] == '확인 필요'


def test_detect_style_and_profile():
    a = asset(review_words(), 60)
    assert guided.detect_style([a], {})[0] == 'oneshot'
    clips = [{'asset_id': 'v', 'start': i * 5, 'end': i * 5 + 3} for i in range(4)]
    profile = guided.learn_profile({'clips': clips}, [a])
    assert profile['median_clip'] == 3 and profile['avg_removed_gap'] == 2
    rules = guided.apply_profile(guided.parse_guideline('', 'vlog'), profile)
    assert rules['max_silent'] == 4.5


def test_clips_are_valid_for_timeline():
    result, _, a = run()
    for clip in result['clips']:
        assert 0 <= clip['start'] < clip['end'] <= a['metadata']['duration']
        assert clip['frame']['mode'] in ('fit', 'fill', 'blur') and clip['id'].startswith('guided-')


def narration_asset(words, duration=30):
    return {'id': 'n', 'name': '나레이션.wav', 'status': 'ready', 'analysis': {'words': tokens(words), 'transcribed': True},
            'metadata': {'duration': duration, 'has_video': False, 'has_audio': True}}


def test_guided_clips_pass_timeline_validation_and_signature():
    result, _, a = run()
    state = {'clips': result['clips'], 'protections': [], 'fps': 30, 'quality': 'standard', 'captions': {'items': []}}
    timeline.validate_state(state, {'v': a})
    assert timeline.signature(state) and timeline.duration(state['clips']) > 0
    assert timeline.export_groups(state, 'cuts')          # 컷별 출력(캡컷 이전용)도 가능


def test_narration_lines_are_pending_and_never_auto_linked():
    n = narration_asset([w(1, ' 먼저 우유를 붓고 전자레인지에 돌려요.', 1, 4), w(2, ' 치즈를 한 장 올려요.', 6, 8)])
    lines = guided.narration_lines(n)
    assert [x['status'] for x in lines] == ['pending', 'pending'] and lines[0]['suggestions'] == []
    assert lines[0]['start'] >= 0.9 and lines[0]['end'] <= 30


def test_link_narration_replaces_overlapping_camera_audio_and_validates():
    result, _, a = run()
    state = {'clips': result['clips'], 'protections': [], 'fps': 30, 'quality': 'standard', 'captions': {'items': []}}
    n = narration_asset([w(1, ' 먼저 우유를 붓고 전자레인지에 돌려요.', 1, 4)])
    line = guided.narration_lines(n)[0]
    assets = {'v': a, 'n': n}
    target = state['clips'][1]                                           # 단면 장면 클립
    visual = {'asset_id': 'v', 'start': target['start'], 'end': target['start'] + 2}
    new_state, warnings = guided.link_narration(state, line, visual, assets)
    timeline.validate_state(new_state, assets)
    linked = [c for c in new_state['clips'] if c['asset_id'] == 'n']
    assert len(linked) == 1 and linked[0]['visual_asset_id'] == 'v'
    assert linked[0]['visual_start'] == target['start']
    # 같은 영상 구간이 원음 클립과 나레이션 클립에 중복으로 남지 않음
    for c in new_state['clips']:
        if c['asset_id'] == 'v' and not c.get('visual_asset_id'):
            assert not (c['start'] < visual['end'] and c['end'] > visual['start'])
    # 재연결해도 클립이 늘어나지 않음
    again, _ = guided.link_narration(new_state, line, visual, assets)
    assert len([c for c in again['clips'] if c['asset_id'] == 'n']) == 1


def test_link_narration_warns_when_visual_is_shorter_than_voice():
    a = asset([], 3)
    n = narration_asset([w(1, ' 아주 긴 나레이션 문장이 이어집니다 정말로 길어요.', 1, 9)])
    line = guided.narration_lines(n)[0]
    state, warnings = guided.link_narration({'clips': [], 'fps': 30}, line, {'asset_id': 'v', 'start': 0, 'end': 3}, {'v': a, 'n': n})
    assert warnings and 'frame' not in ''.join(warnings).lower()


def test_exports_edl_fcpxml_and_import_order():
    import xml.etree.ElementTree as ET
    from studio import exports
    edit_list = [{'edited_start': 0, 'edited_end': 3.5, 'label': '1. 제품 소개', 'source_name': 'a.mp4', 'original_start': 7.9, 'original_end': 11.4},
                 {'edited_start': 3.5, 'edited_end': 10, 'label': '2. 단면', 'source_name': 'a.mp4', 'original_start': 12, 'original_end': 18.5}]
    groups = [{'file': 'out.mp4', 'start': 0, 'end': 10, 'label': '전체 컷편집본'}]
    files = exports.package(edit_list, groups, 30, 'out')
    assert set(files) == {'import-order.txt', 'out.edl', 'out.fcpxml', 'out_cut-markers.txt'}
    assert '00:00:03:15 00:00:10:00' in files['out.edl'] and files['out.edl'].count('FROM CLIP NAME') == 2
    root = ET.fromstring(files['out.fcpxml'])                       # 올바른 XML
    clips = root.findall('.//asset-clip')
    assert len(clips) == 2 and clips[1].get('offset') == '105/30s' and clips[1].get('duration') == '195/30s'
    assert '원본 a.mp4' in files['import-order.txt'] and '00:00:03.500' in files['out_cut-markers.txt']
    # 컷별 출력은 EDL 없이 가져오기 순서만
    many = exports.package(edit_list, [{'file': '001_a.mp4', 'start': 0, 'end': 3.5, 'label': 'a'}, {'file': '002_b.mp4', 'start': 3.5, 'end': 10, 'label': 'b'}], 30, 'out')
    assert set(many) == {'import-order.txt'} and '02. 002_b.mp4' in many['import-order.txt']


def test_five_takes_keep_cleanest():
    """같은 문장을 5번 말하면 발음이 가장 또렷한(신뢰도 높고 군말·더듬음 없는) 테이크 하나만 남는다."""
    text = ' 이거 식감이 쫄깃하고 촉촉해서 진짜 맛있어요.'
    takes = [
        ([w(1, ' 이거 식감이 쫄깃', 0, 1.5, .9)], 'fragment'),
        ([w(2, ' 이거 식감이 쫄깃하고 음 촉촉해서 진짜 맛있어요.', 3, 7, .7)], 'filler'),
        ([w(3, text, 9, 12, .97)], 'best'),
        ([w(4, ' 이거 식감이 쫄깃하고 촉촉해서 진짜 진짜 맛있어요.', 14, 18, .8)], 'stutter'),
        ([w(5, text, 20, 23.5, .6)], 'mumbled'),
    ]
    words = []
    for group, _ in takes:
        words += tokens(group)
    sentences = guided.split_sentences(words, 30)
    guided.mark_redundant(sentences)
    kept = [s for s in sentences if not s['drop']]
    assert len(kept) == 1, [(s['text'], s['drop']) for s in sentences]
    assert kept[0]['start'] == 9 and kept[0]['takes'] == 5
    assert all(s['drop'] for s in sentences if s['start'] != 9)


def test_different_numbers_not_treated_as_retake():
    words = tokens([w(1, ' 가격은 2500원이에요.', 0, 2), w(2, ' 가격은 3500원이에요.', 4, 6)])
    sentences = guided.mark_redundant(guided.split_sentences(words, 10))
    assert not any(s['drop'] for s in sentences)


def test_commentary_style_and_viewer_question():
    assert 'commentary' in guided.STYLES and guided.GUIDELINES['commentary'] != guided.GUIDELINES['default']
    rules = guided.parse_guideline(guided.GUIDELINES['commentary'], 'commentary')
    assert rules['target'] == (45, 60) or rules['target']
    ask = guided.classify('여러분은 가오나시를 어떻게 보셨나요?')
    assert 'conclusion' in ask['labels'] and 'question' in ask['labels']
    assert 'conclusion' not in guided.classify('댓글로 요청받은 과자 먹어봤습니다')['labels']
    why = guided.classify('가오나시는 왜 치히로에게 금을 줬을까요?')
    assert 'question' in why['labels']


def test_score_verdict_is_classified_and_never_trimmed():
    assert 'score' in guided.classify('8점 드릴게요')['labels']
    assert 'score' in guided.classify('이건 5점 드릴게요.')['labels']
    assert 'score' not in guided.classify('이 점이 좋았어요')['labels']
    assert 'score' not in guided.classify('장점이 많아요')['labels']
    words, t = [], 1
    for i in range(50):
        words.append(w(i, f' 일반 이야기 {i}번째 문장이에요.', t, t + 2))
        t += 3
        if i == 10:
            words.append(w(500, ' 이건 8점 드릴게요.', t, t + 1.5))
            t += 2.5
    result, _, _ = run(words, duration=t + 5)
    assert any('score' in u['labels'] for u in result['units'])


def test_eating_shot_is_laid_over_later_taste_comment_and_not_repeated():
    # 먹고 나서 잠깐 다른 말을 한 뒤(12초 안) 평가: 시식 구간이 아니라 먹는 화면을 평가 위에 얹는다.
    words = [w(1, ' 오늘은 편의점 신상 찹쌀떡을 먹어볼게요.', 2, 5), w(4, ' 오 이거 크기가 커요.', 21, 22.5),
             w(2, ' 식감이 정말 쫄깃하고 맛있어요.', 30, 33),        # 먹고 나서 말한 평가 → 먹는 화면을 얹는다
             w(3, ' 이건 8점 드릴게요.', 36, 38)]                    # 점수는 얼굴 화면 그대로
    frames = [frame(0, 14, 16, {'eating': .3}, shot=1), frame(1, 16, 18, {'eating': .3}, shot=1)]
    result, _, a = run(words, frames=frames, duration=45)
    timeline.validate_state({'clips': result['clips'], 'fps': 30, 'quality': 'standard', 'protections': []}, {'v': a})
    over = [c for c in result['clips'] if c.get('visual_asset_id')]
    assert len(over) == 1
    c = over[0]
    assert 29 < c['start'] < 31 and 32 < c['end'] < 34           # 소리는 평가 발화
    assert 13.9 <= c['visual_start'] < 15 and c['visual_end'] <= 18.01   # 화면은 먹는 장면
    assert abs((c['visual_end'] - c['visual_start']) - (c['end'] - c['start'])) < .45
    plain = [c for c in result['clips'] if not c.get('visual_asset_id')]
    assert not any(c['start'] < 18 and c['end'] > 14 for c in plain)   # 얹은 시식 컷이 단독으로 또 나오지 않음
    assert any(35 < c['start'] < 37 for c in plain)                    # 점수 발화는 원래 화면
    assert any('화면을 얹었어요' in n for n in result['warnings'])


def test_short_eating_shot_covers_only_the_start_of_a_long_comment():
    words = [w(2, ' 오 이거 크기가 커요.', 23, 24.5), w(1, ' 식감이 정말 쫄깃하고 촉촉하고 부드럽고 달달해서 계속 먹게 되는 맛이에요.', 30, 36)]
    frames = [frame(0, 20, 21.5, {'eating': .3}, shot=1)]
    result, _, _ = run(words, frames=frames, duration=45)
    over = [c for c in result['clips'] if c.get('visual_asset_id')]
    assert len(over) == 1 and over[0]['end'] - over[0]['start'] < 2.1
    rest = [c for c in result['clips'] if not c.get('visual_asset_id') and c['start'] >= over[0]['end'] - .05]
    assert rest and rest[0]['end'] > 35.5       # 남는 뒷부분은 원래 화면으로 이어짐


def test_speech_tail_follows_fading_voice():
    db = [60.] * 1000
    env = {'rate': 100, 'db': db, 'floor': 20., 'voice': 60.}
    for i in range(523, 1000):
        db[i] = 20.                      # 5.0초에 단어가 끝났다고 인식됐지만 실제 소리는 5.23초까지 이어짐
    tail = guided.speech_tail(env, 5.0)
    assert .25 <= tail <= .32, tail
    for i in range(500, 1000):
        db[i] = 20.                      # 바로 끝나도 최소 0.15초
    assert guided.speech_tail(env, 5.0) == guided.TAIL_MIN
    for i in range(500, 1000):
        db[i] = 60.                      # 계속 소리가 나면 최대 0.35초
    assert guided.speech_tail(env, 5.0) == guided.TAIL_MAX
    assert guided.speech_tail(None, 5.0) == guided.TAIL_DEFAULT


def test_default_tail_is_longer_than_word_end():
    result, _, _ = run([w(1, ' 이건 정말 맛있어요.', 10, 12), w(2, ' 다음 이야기를 해볼게요.', 20, 22)], duration=30)
    speech = [u for u in result['units'] if u['kind'] == 'speech']
    assert all(u['end'] - (12 if u['start'] < 15 else 22) >= .24 for u in speech)


def two_takes(words, frames, detail_frames, evidence=None, style='oneshot', face_talk=False):
    """말하는 원본 v + 말 없이 따로 찍은 디테일 컷 원본 d(완성본 1123 촬영 방식)."""
    v = asset(words, 130)
    d = {**asset([], 60, name='디테일.mp4', ident='d'), }
    d['analysis']['speech'] = []
    rules = guided.parse_guideline(default_guideline(), style)
    rules['face_talk'] = face_talk   # 기본(얼굴) 동작은 test_talking_always_shows_the_face_and_narration_only_over_eating
    return guided.plan([v, d], rules, {'v': frames, 'd': detail_frames}, evidence or {}), v, d


HOOK_WORDS = [w(1, ' 편의점 신상 찹쌀떡 네 가지를 전부 먹어볼게요.', 1, 6)] + \
             [w(10 + i, f' 일반 이야기 {i}번째 문장이에요.', 10 + 3 * i, 12 + 3 * i) for i in range(10)]


def test_opening_never_chops_one_word_into_random_same_take_pieces():
    # 사용자 피드백 '초반에 왜 그럼': 같은 원본의 장면을 0.28초 조각으로 바꿔 끼우던 방식은 쓰지 않는다.
    frames = [frame(i, 40 + 8 * i, 41.5 + 8 * i, {'packaging': .3}, shot=10 + i) for i in range(5)]
    result, _, _ = run(HOOK_WORDS, frames=frames, duration=130)
    head = [c for c in result['clips'] if c['start'] < 6.5]
    assert all(c['end'] - c['start'] >= .7 for c in head), head
    assert not any(c.get('visual_asset_id') == 'v' and c.get('visual_start') != c['start'] for c in head)


def test_opening_shows_product_lineup_from_detail_take():
    lineup = [frame(i, 10 + .5 * i, 10.5 + .5 * i, {'comparison': .3}, shot=1) for i in range(4)] + \
             [frame(10 + i, 30 + .5 * i, 30.5 + .5 * i, {'comparison': .3}, shot=2) for i in range(4)]
    result, v, d = two_takes(HOOK_WORDS, [], lineup)
    timeline.validate_state({'clips': result['clips'], 'fps': 30, 'quality': 'standard', 'protections': []}, {'v': v, 'd': d})
    head = sorted((c for c in result['clips'] if c.get('visual_asset_id') == 'd' and c['start'] < 6), key=lambda c: c['start'])
    assert len(head) >= 2, result['clips'][:4]
    assert all(.79 <= c['end'] - c['start'] <= 1.21 for c in head)             # 0.8~1.2초씩
    assert all(c['asset_id'] == 'v' for c in head)                            # 소리는 첫 멘트 그대로
    for c, e in zip(head, head[1:]):
        assert abs(e['start'] - c['end']) < 1e-6                               # 소리 끊김 없음
    assert any('1123' in n for n in result['warnings'])


def test_detail_shot_lands_only_on_the_same_product_line():
    words = [w(1, ' 오늘은 편의점 디저트 두 개를 먹어볼게요.', 1, 4),
             w(2, ' 먼저 소금우유는 밀크초콜릿에 캐러멜칩이 들어갔대요.', 10, 14),
             w(3, ' 이건 8점 드릴게요.', 20, 22),
             w(4, ' 다음은 호지차인데 겉에 녹차 파우더가 묻어 있어요.', 30, 34),
             w(5, ' 이건 6점 드릴게요.', 40, 42)]
    frames = [frame(1, 10, 14, {}, shot=1), frame(2, 30, 34, {}, shot=2)]
    detail = [frame(10, 5, 6.5, {'packaging': .3}, shot=5), frame(11, 20, 21.5, {'packaging': .3}, shot=6)]
    ev = {('v', frames[0]['id']): [{'name': '소금우유', 'status': 'confirmed'}],
          ('v', frames[1]['id']): [{'name': '호지차', 'status': 'confirmed'}],
          ('d', detail[0]['id']): [{'name': '호지차', 'status': 'confirmed'}],
          ('d', detail[1]['id']): [{'name': '소금우유', 'status': 'confirmed'}]}
    result, _, _ = two_takes(words, frames, detail, ev)
    laid = [c for c in result['clips'] if c.get('visual_asset_id') == 'd']
    assert laid, result['clips']
    for c in laid:
        line = 'salt' if c['start'] < 16 else 'hoji'
        assert (20 <= c['visual_start'] <= 21.5) == (line == 'salt'), c       # 다른 제품 디테일 컷은 섞지 않음
    assert not any(c.get('visual_asset_id') == 'd' and 20 <= c['start'] < 23 for c in result['clips'])   # 점수는 얼굴


def test_food_only_effects_are_off_for_commentary_and_vlog():
    for style, on in (('oneshot', True), ('cook_mukbang', True), ('restaurant', True), ('commentary', False), ('vlog', False)):
        rules = guided.parse_guideline(default_guideline(), style)
        assert rules['overlay_eating'] is on and rules['hook_montage'] is on, style
    assert guided.parse_guideline(default_guideline(), 'recipe')['hook_montage']
    assert not guided.parse_guideline(default_guideline() + '\n몽타주 빼줘', 'oneshot')['hook_montage']


def test_commentary_is_simple_tight_cut_with_best_take_and_kept_endings():
    words = [w(1, ' 이 장면은 사실', 1.0, 2.0), w(2, ' 복선이었어요.', 2.6, 3.4),          # 문장 안 0.6초 쉼 → 빼기
             w(3, ' 오디세우스가 돌아온 이유는', 6.0, 7.5), w(4, ' 오디세', 7.6, 7.9),       # 버벅임 → 다시 말함
             w(5, ' 오디세우스가 돌아온 이유는 가족 때문이에요.', 10.0, 12.5),
             w(6, ' 여러분은 어떻게 보셨나요?', 16.0, 18.0)]
    rules = guided.parse_guideline(guided.DEFAULT_GUIDELINE_COMMENTARY_OLD, 'commentary')
    assert rules['tight'] and rules['no_trim'] and rules['hook'] == 'none' and not rules['hook_montage']
    a = asset(words, 30)
    result = guided.plan([a], rules, {'v': []}, {})
    clips = result['clips']
    timeline.validate_state({'clips': clips, 'fps': 30, 'quality': 'standard', 'protections': []}, {'v': a})
    covered = lambda t: any(c['start'] <= t < c['end'] for c in clips)
    assert covered(1.5) and covered(3.0) and covered(11) and covered(17)
    assert not covered(2.35)                   # 문장 안 무음 제거
    assert any('무음 제거' in a for a in rules['applied'])
    assert not covered(5.0) and not covered(14.5)   # 문장 사이 무음 제거
    assert not covered(6.5)                    # 버벅인 첫 시도 제거, 다시 말한 쪽만
    for end in (3.4, 12.5, 18.0):              # 말끝 보존(0.2초 이상 여유)
        assert covered(end + .18), end
    starts = [c['start'] for c in clips]
    assert starts == sorted(starts)            # 말한 순서 그대로


KK = """업로드한 KK뷰티페스타·KGMA 현장 영상에서 중요한 부분을 골라 세로 9:16 숏폼으로 편집해줘.

목표 길이는 45~60초로 하되, 현장 멘트나 문장 끝을 자르면서 억지로 길이를 맞추지 마.

남길 장면 (이 순서로 배치):
1. 첫 장면: 팔로우 이벤트로 받은 물건을 전부 펼친 샷. 본품 패키지 앞면이 보이는 구간을 우선으로 골라줘.
2. KK뷰티페스타 캡슐 뽑기 부스 전경과 뽑기 차례를 기다리는 장면
3. 부스 진행자가 외국인 관객에게 말을 거는 장면. 현장음을 그대로 살리고 웃긴 한마디가 끝날 때까지 자르지 마.
4. 1분 캡슐 뽑기: 캡슐 뽑는 손과 4등·5등 결과가 나오는 장면
5. 4등 레몬약과와 5등 브라우니를 손에 들고 보여주는 컷. 먹는 장면은 없으니 찾지 말고 들고 있는 컷만 써.
6. KGMA 현장: 다영, 영케이, 리센느, 트리플에스 무대를 각각 짧게
7. 장면 전환용 풍경 컷이 있으면 짧게 넣고, 없으면 건너뛰어
마지막: 사은품 전체 샷에 이어 본품 클로즈업

줄일 부분:
- 촬영 준비, 카메라 조정, 의미 없는 대기
- 말실수 후 다시 말한 경우 앞의 실패한 부분

단, 사은품·본품 클로즈업, 캡슐 결과, 무대 장면은 음성이 없다는 이유만으로 삭제하지 마.

자막·표기:
- 자막은 영상에서 실제로 말한 내용 그대로 달기. 현장 멘트에도 자막 달기.
- 화면 상단에 '유료광고 포함'을 처음부터 끝까지 표시
- KK뷰티페스타 부스가 처음 나올 때 'KK뷰티페스타', KGMA 현장이 처음 나올 때 'KGMA' 표시
- 첫 장면 강조 자막: 본품까지 준다고?

구성:
- KK뷰티페스타 장면과 KGMA 장면을 섞지 말고 행사별로 묶기
- 마지막은 본품 클로즈업에서 끝내기

실제로 말하지 않은 평가나 결론은 만들지 말고, 먼저 추천 편집본을 만들어 내가 확인할 수 있게 해줘."""


def test_instruction_sheet_scene_list_is_parsed():
    rules = guided.parse_guideline(KK, 'vlog')
    sc = rules['scenes']
    assert len(sc) == 8 and sc[0]['first'] and sc[-1]['last']
    assert sc[2]['live'] and not sc[0]['live']
    assert sc[4]['absent'] == ['eating'] and 'eating' not in sc[4]['roles']
    assert sc[5]['count'] == 4 and sc[5]['short']
    assert sc[6]['optional'] and not sc[1]['optional']
    assert '진행자' in sc[2]['terms'] and '외국인' in sc[2]['terms']
    kinds = {o['kind']: o['text'] for o in rules['overlays']}
    assert kinds['fixed'] == '유료광고 포함' and kinds['emphasis'] == '본품까지 준다고?'
    assert {o['text'] for o in rules['overlays'] if o['kind'] == 'name'} == {'KK뷰티페스타', 'KGMA'}
    assert rules['target'] == (45, 60) and rules['hook'] == 'none'


def test_scene_list_orders_edit_and_respects_live_absent_and_marks():
    words = [w(1, ' 진행자가 외국인 관객에게 어디서 왔어요 하고 물어봤어요.', 30, 33),
             w(2, ' 저 미국에서 왔어요 하하.', 33.3, 35),                  # 이어지는 현장 멘트 → 함께
             w(3, ' 여기 KK뷰티페스타 캡슐 뽑기 부스예요.', 10, 13),
             w(4, ' 본품 패키지까지 전부 펼쳐 봤어요.', 2, 5),
             w(5, ' 레몬약과 먹는 중이에요 맛있어요.', 70, 72),             # 먹는 장면: 5번 장면에 쓰면 안 됨
             w(6, ' 4등 레몬약과랑 5등 브라우니를 들고 보여드릴게요.', 60, 63),
             w(7, ' 1분 캡슐 뽑기 결과 4등 5등 나왔어요.', 50, 53),
             w(8, ' 마지막으로 사은품 전체랑 본품 클로즈업이에요.', 90, 93)]
    rules = guided.parse_guideline(KK, 'vlog')
    a = asset(words, 100)
    result = guided.plan([a], rules, {'v': []}, {})
    texts = [u['text'].strip() for u in result['units']]
    order = [t for t in texts]
    assert order.index('본품 패키지까지 전부 펼쳐 봤어요.') == 0                      # 첫 장면
    assert order[-1] == '마지막으로 사은품 전체랑 본품 클로즈업이에요.'                  # 마지막
    i = order.index('진행자가 외국인 관객에게 어디서 왔어요 하고 물어봤어요.')
    assert order[i + 1] == '저 미국에서 왔어요 하하.'                                    # 현장 멘트 끝까지
    assert order.index('여기 KK뷰티페스타 캡슐 뽑기 부스예요.') < i < order.index('1분 캡슐 뽑기 결과 4등 5등 나왔어요.')
    assert '레몬약과 먹는 중이에요 맛있어요.' not in texts                               # '먹는 장면은 없으니 찾지 마'
    assert any('KGMA' in w and '찾지 못했어요' in w for w in result['warnings'])          # 6번은 원본에 없음 → 알림
    assert not any('풍경' in w for w in result['warnings'])                               # 선택 장면은 조용히 건너뜀
    marks = guided.overlay_items(result['overlays'], result['clips'])
    by = {m['text']: m for m in marks}
    assert by['유료광고 포함']['start'] == 0 and by['유료광고 포함']['end'] > 10
    assert by['본품까지 준다고?']['start'] == 0
    assert 'KK뷰티페스타' in by and by['KK뷰티페스타']['start'] > 0
    assert any('KGMA' in w and '표기' in w for w in result['warnings'])                  # 위치 못 찾은 표기는 알림


def test_default_guideline_oneshot_mukbang():
    rules = guided.parse_guideline(guided.DEFAULT_GUIDELINE, 'oneshot')
    assert rules['target'] == (45, 60)
    assert rules['group_products']
    assert {'opening', 'crosssection', 'eating'} <= rules['keep']


def test_storyboard_target_overrides_template_length():
    storyboard_guideline = guided.storyboard_guideline
    text = storyboard_guideline(guided.DEFAULT_GUIDELINE, '편집 구성표\n목표 65초. 시식 멘트까지 포함해 원 녹음이 82초라면')
    assert guided.parse_guideline(text, 'oneshot')['target'] == (55, 65)
    assert storyboard_guideline(guided.DEFAULT_GUIDELINE, '') == guided.DEFAULT_GUIDELINE
    assert storyboard_guideline(guided.DEFAULT_GUIDELINE, '그냥 메모') == guided.DEFAULT_GUIDELINE


def test_every_type_has_its_own_default_guideline():
    from studio.guided_texts import TYPE_GUIDELINES
    assert set(TYPE_GUIDELINES) == set(guided.STYLES)
    for key, text in TYPE_GUIDELINES.items():
        rules = guided.parse_guideline(text, key)
        assert key == 'commentary' or rules['target'] == (45, 60), key
        assert guided.is_default_text(text)
    assert guided.is_default_text(guided.DEFAULT_GUIDELINE_GENERAL)
    assert not guided.is_default_text('내가 고친 지침')
    # 새 유형의 지침도 해설 유형 지침도 오래된 기본 지침으로 인식된다
    assert guided.default_for('product_mukbang').startswith('업로드한 먹방 리뷰 영상과 제품 디테일 컷')


# ------------------------------------------------ 실제 목소리(VAD) 기준 경계 · 무음 · 겹침
def test_snap_to_voice_pulls_late_first_word_and_trims_silent_tail():
    # 실제 원본(1122)에서 본 모양: 인식기는 325.64~329.74로 찍었지만 실제 목소리는 324.66~325.56, 326.97~329.11.
    voice = [(320.0, 321.0), (324.66, 325.56), (326.97, 329.11), (334.71, 336.25)]
    s, e, gaps = guided.snap_to_voice(325.64, 329.74, voice, lo=321.2, hi=334.78)
    assert s == 324.66                       # 첫 단어('단짠단짠한데')를 자르지 않는다
    assert e == 329.11                       # 끝의 0.6초 무음은 빼고 말끝 여유는 나중에 더한다
    assert gaps == [(325.56, 326.97)]        # 문장 안 1.4초 쉼
    # 앞 문장 영역(lo)은 넘어가지 않는다
    s, _, _ = guided.snap_to_voice(325.64, 329.74, voice, lo=325.0, hi=334.78)
    assert s >= 325.0


def test_snap_to_voice_keeps_whisper_when_vad_is_weak():
    # 배경 소음이 커서 VAD가 1.16초 중 0.29초만 잡으면 0.25초까지만 줄인다.
    s, e, _ = guided.snap_to_voice(15.91, 17.07, [(16.35, 16.64)])
    assert abs(s - 16.16) < 1e-6 and abs(e - 16.82) < 1e-6
    assert guided.snap_to_voice(5, 6, []) == (5, 6, [])


def _voice_asset(words, voice, duration=60):
    a = asset(words, duration)
    a['analysis']['speech'] = [list(v) for v in voice]
    return a


def test_long_pause_inside_sentence_is_shortened_and_clips_never_overlap():
    words = [w(1, ' 오늘은 편의점 신상 크림빵을 먹어볼게요.', 8, 11), w(2, ' 이거 식감이 쫄깃하고 촉촉해서 맛있어요.', 20.4, 25.6),
             w(3, ' 다시 사 먹고 싶어요.', 30, 32)]
    voice = [(8.1, 10.6), (20.0, 21.5), (23.5, 25.0), (30.0, 31.8)]   # 2번 문장 안 2초 쉼, 인식기 끝은 0.6초 늦음
    a = _voice_asset(words, voice)
    rules = guided.parse_guideline(default_guideline(), 'oneshot')
    clips = guided.plan([a], rules, {'v': []}, {})['clips']
    spans = sorted((c['start'], c['end']) for c in clips)
    assert all(x[1] <= y[0] + 1e-9 for x, y in zip(spans, spans[1:]))     # 같은 소리가 두 번 나지 않음
    covered = lambda t: any(c0 <= t <= c1 for c0, c1 in spans)
    assert covered(20.0) and covered(21.5) and covered(23.5) and covered(25.0)   # 문장 앞뒤 목소리는 다 남김
    assert not covered(22.5)                                                    # 2초 쉼 한가운데는 뺌
    assert not any(c0 < 25.6 < c1 for c0, c1 in spans) or max(c1 for c0, c1 in spans if c0 < 25.6) <= 25.0 + guided.TAIL_MAX + .05


def test_adjacent_clips_do_not_overlap_after_frame_rounding():
    units = [{'kind': 'speech', 'asset_id': 'v', 'filename': 'x', 'start': 1.01, 'end': 2.015, 'role': 'taste', 'labels': ['taste'],
              'text': 'a', 'review': [], 'visual_roles': [], 'overlay': {'start': 10., 'end': 10.5, 'role': 'eating'}}]
    a = asset([], 30)
    clips = guided._merge_clips(units, [a], {'frame': 'auto', 'tight': False}, 30)
    assert len(clips) == 2
    assert clips[0]['end'] <= clips[1]['start'] + 1e-9


def test_mukbang_eating_shows_under_taste_narration():
    # 1122 원본 모양: 제품을 바꿔 한참 말없이 먹고(먹기 프레임 40초) 나서 맛을 말한다.
    # 말없이 먹는 장면을 따로 넣지 않고, 먹는 화면 위에 바로 뒤 소감 목소리를 깐다(나레이션).
    words = [w(1, ' 오늘은 편의점 신상 초콜릿을 먹어볼게요.', 2, 5), w(2, ' 단짠단짠한데 크런키한게 씹혀요.', 50, 53),
             w(3, ' 이건 8점 드릴게요.', 56, 58)]
    voice = [(2, 4.8), (50, 52.7), (56, 57.8)]
    a = _voice_asset(words, voice, duration=70)
    frames = [frame(1, 40, 41, {'eating': .9}, shot=3)]
    rules = guided.parse_guideline(guided.default_for('product_mukbang'), 'product_mukbang')
    out = guided.plan([a], rules, {'v': frames}, {})
    narr = [c for c in out['clips'] if c.get('visual_asset_id')]
    assert len(narr) == 1
    n = narr[0]
    assert n['start'] < 50.2 and n['end'] > 51          # 소리는 소감 발화
    assert n['visual_start'] < 40.2 < n['visual_end']   # 화면은 먹는 순간
    assert '나레이션' in n['guided']['units'][0]['reason']
    # 말없이 먹는 장면을 소리째 따로 넣지 않는다
    assert not any(c['start'] < 49.5 and c['end'] > 39.5 and not c.get('visual_asset_id') for c in out['clips'])
    # 남은 소감과 점수는 얼굴 화면
    assert any(not c.get('visual_asset_id') and c['start'] <= 57 <= c['end'] for c in out['clips'])


def test_product_intro_and_ingredients_survive_length_trim():
    # 제품마다: 들고 소개 → 구성 설명 → (먹고) 평가 → 점수. 길이가 넘쳐도 소개·구성 설명은 남긴다('먹방만 넣으면 안 된다').
    words = []
    t = 2
    for n, name in enumerate(['CU 소금우유', 'GS 호지차', '이마트24 허니페어', '세븐일레븐 크림브륄레']):
        words += [w(10 * n + 1, f' 먼저 {name}는', t, t + 2), w(10 * n + 2, ' 안에 캐러멜칩이 들어갔다는데', t + 3, t + 5),
                  w(10 * n + 3, ' 그냥 여기 이렇게 놓고요', t + 6, t + 9),
                  w(10 * n + 4, ' 진짜 맛있어요 식감이 좋아요', t + 40, t + 45), w(10 * n + 5, ' 고소하고 달달한 맛이에요', t + 47, t + 52),
                  w(10 * n + 6, ' 이건 8점 드릴게요.', t + 55, t + 57)]
        t += 70
    rules = guided.parse_guideline(guided.default_for('product_mukbang'), 'product_mukbang')
    out = guided.plan([asset(words, duration=t + 10)], rules, {'v': []}, {})
    kept = ' '.join(u['text'] for u in out['units'])
    assert kept.count('캐러멜칩이 들어갔다는데') == 4
    assert all(name in kept for name in ['CU', 'GS', '이마트24', '세븐일레븐'])
    assert kept.count('8점') == 4


def test_short_fragment_is_not_mistaken_for_a_retake():
    words = [w(1, ' 먼저 CU 소금우유는', 2, 4), w(2, ' 밀크초콜릿에', 5, 6), w(3, ' 소금우유', 7, 8), w(4, ' 필링까지 들어갔다는데', 9, 11)]
    sentences = guided.mark_redundant(guided.split_sentences(guided_tokens(words), 20))
    assert not any(s['drop'] for s in sentences)


def guided_tokens(words):
    return tokens(words)


def test_target_is_final_length_after_capcut_speed_up():
    # 완성본 1123: 캡컷 1.3배속 · 62.8초 = 원본 분량 약 82초. 목표 길이를 배속 전 길이로 맞추면 평가 문장이 너무 빠진다.
    assert guided.parse_guideline(default_guideline(), 'oneshot')['playback'] == 1.3
    assert guided.parse_guideline('1.4배속으로 올릴 거야', 'oneshot')['playback'] == 1.4
    assert guided.parse_guideline('배속 없이', 'oneshot')['playback'] == 1
    assert guided.parse_guideline(default_guideline(), 'commentary')['playback'] == 1


def test_length_trim_keeps_opinion_over_bare_exclamation():
    words = [w(1, ' 오늘은 소금우유 초콜릿을 먹어볼게요.', 1, 4)]
    t = 10
    for i in range(14):
        words.append(w(10 + i, ' 맛있다.' if i % 2 else ' 저는 크런키한 식감이 좋더라고요.', t, t + 2.5))
        t += 6
    words.append(w(99, ' 이건 8점 드릴게요.', t, t + 2))
    result, rules, _ = run(words, guideline='20초', duration=t + 5)
    texts = [u['text'] for u in result['units']]
    assert any('좋더라고요' in x for x in texts)
    gone = [r['text'] for r in result['removed'] if r['reason_code'] == 'length']
    assert gone and sum('맛있다' in x for x in gone) >= sum('좋더라고요' in x for x in gone)


def test_untranscribed_repeat_inside_a_sentence_is_cut():
    # 실제 원본 134~144초: '필링까지'가 8초짜리 한 단어로 찍혔고 그 사이 목소리 구간은 같은 말을 다시 시작한 부분(두 번 들림).
    a = asset([], 160)
    a['analysis']['words'] = [{'id': 'a', 'text': ' 필링까지', 'start': 133.24, 'end': 141.58, 'confidence': .9},
                              {'id': 'b', 'text': ' 캐러멜칩이', 'start': 141.58, 'end': 143.46, 'confidence': .9},
                              {'id': 'c', 'text': ' 들어갔다는데.', 'start': 143.46, 'end': 144.78, 'confidence': .9}]
    a['analysis']['speech'] = [[134.84, 135.03], [135.35, 136.63], [138.42, 139.67], [140.31, 141.56], [142.81, 144.31]]
    rules = guided.parse_guideline(default_guideline(), 'oneshot')
    result = guided.plan([a], rules, {'v': []}, {})
    heard = []
    for c in result['clips']:
        heard += [(x0, x1) for x0, x1 in a['analysis']['speech'] if c['start'] < x1 and c['end'] > x0]
    assert (138.42, 139.67) in [tuple(x) for x in heard] and (142.81, 144.31) in [tuple(x) for x in heard]
    assert not any(x0 < 137 for x0, _ in heard), result['clips']     # 앞의 반복 시도는 빠짐


def test_skip_swallowed_keeps_pieces_where_other_words_start():
    # '저는 크런키한(1.7초) 식감이 좋더라고요': 두 구간 모두 다른 단어가 시작하므로 하나도 빼지 않는다.
    s0, gaps = guided.skip_swallowed(1127.77, 1131.1, [(1128.34, 1128.89)],
                                     [(1127.90, 1127.98), (1127.98, 1129.68), (1129.68, 1130.18), (1130.18, 1131.46)])
    assert s0 == 1127.77 and gaps == [(1128.34, 1128.89)]


def test_eating_overlay_never_crosses_into_the_next_product():
    # 점수 뒤(다음 제품) 먹는 화면을 앞 제품 소감 위에 얹지 않는다.
    words = [w(1, ' 오늘은 초콜릿 두 개를 먹어볼게요.', 1, 4),
             w(2, ' 단짠단짠해서 맛있네요.', 20, 23),
             w(3, ' 이건 8점 드릴게요.', 30, 32),
             w(4, ' 다음은 호지차예요.', 40, 42)]
    frames = [frame(1, 34, 37, {'eating': .4}, shot=5)]
    result, _, _ = run(words, frames=frames, duration=60)
    taste = [c for c in result['clips'] if c['start'] < 24 and c['end'] > 20]
    assert not any(c.get('visual_start', c['start']) >= 32 for c in taste), taste


def test_auto_products_names_each_product_from_its_intro_and_matches_box_text():
    # 제품 등록이 없어도: 점수로 나뉜 제품 구간마다 소개 말에서 이름을 뽑고, 디테일 컷 포장 글자(OCR)와 맞춘다.
    words = [w(1, ' 먼저 소금우유는 밀크초콜릿에 캐러멜칩이 들어갔대요.', 10, 14), w(2, ' 이건 8점 드릴게요.', 20, 22),
             w(3, ' 다음은 호지차인데 겉에 녹차 파우더가 묻어 있어요.', 30, 34), w(4, ' 이건 6점 드릴게요.', 40, 42),
             w(5, ' 둘 다 맛은 있는데 묶어서 팔아 주세요.', 50, 53)]
    v = asset(words, 60)
    d = asset([], 40, name='디테일.mp4', ident='d')
    d['analysis']['speech'] = []
    def row(i, t, text):
        r = frame(i, t, t + .5, {'packaging': .3}, shot=1)
        r['ocr'] = [{'text': text}]
        return r
    detail = [row(1, 2, 'PREMIUM 호지지'), row(2, 2.5, ''), row(3, 3, 'Ghana'), row(4, 20, '소금우유'), row(5, 20.5, 'Cafe'), row(6, 21, ''),
              row(7, 30, '소금우유 호지차')]   # 상자 두 개가 함께 보이면 어느 한 제품 컷으로 쓰지 않는다
    rules = guided.parse_guideline(default_guideline(), 'oneshot')
    rules['face_talk'] = False   # 설명 위 디테일 컷 동작 확인(기본은 말할 때 얼굴)
    result = guided.plan([v, d], rules, {'v': [], 'd': detail}, {})
    laid = {round(c['start']): c['visual_start'] for c in result['clips'] if c.get('visual_asset_id') == 'd'}
    salt = [vs for s, vs in laid.items() if s < 16]
    hoji = [vs for s, vs in laid.items() if 28 < s < 36]
    assert salt and all(19 <= x <= 22 for x in salt), laid
    assert hoji and all(1 <= x <= 4 for x in hoji), laid
    assert not any(29 <= x <= 31 for x in laid.values())


def test_post_narration_marker_reserves_opening_with_product_shots():
    # 사용자: 초반 후킹 나레이션은 캡컷 후작업. 이름·지침에 '후 나레이션'이 있을 때만 첫 부분을 비슷한 장면으로 채운다.
    assert guided.parse_guideline('후 나레이션 포함', 'oneshot')['post_narration']
    assert not guided.parse_guideline(default_guideline(), 'oneshot')['post_narration']
    assert not guided.parse_guideline('후 나레이션 없이', 'oneshot')['post_narration']
    words = [w(1, ' 먼저 소금우유는 밀크초콜릿이에요.', 10, 13), w(2, ' 이건 8점 드릴게요.', 20, 22),
             w(3, ' 다음은 호지차예요.', 30, 32), w(4, ' 이건 6점 드릴게요.', 40, 42)]
    v = asset(words, 60)
    d = asset([], 60, name='디테일.mp4', ident='d')
    d['analysis']['speech'] = []
    def row(i, t, text, tags):
        r = frame(i, t, t + .5, tags, shot=1)
        r['ocr'] = [{'text': text}]
        return r
    detail = [row(i, 2 + .5 * i, '', {'comparison': .3}) for i in range(6)] + \
             [row(20 + i, 20 + .5 * i, '소금우유', {'packaging': .3}) for i in range(4)] + \
             [row(30 + i, 40 + .5 * i, '호지지', {'packaging': .3}) for i in range(4)]
    for text, slot in (('후 나레이션 포함', True), ('', False)):
        rules = guided.parse_guideline(default_guideline() + '\n' + text, 'oneshot')
        result = guided.plan([v, d], rules, {'v': [], 'd': detail}, {})
        first = sorted(result['clips'], key=lambda c: c.get('timeline_start', 0))[:3]
        opening = [c for c in result['clips'] if c['asset_id'] == 'd']
        if slot:
            assert result['clips'][0]['asset_id'] == 'd' and len(opening) >= 3      # 말하는 원본보다 먼저, 원본 소리
            assert any(19 <= c['start'] <= 22 for c in opening) and any(39 <= c['start'] <= 42 for c in opening)
        else:
            assert result['clips'][0]['asset_id'] == 'v'


def test_same_scene_is_never_shown_twice_and_detail_shots_spread_over_the_product_take():
    # 사용자 피드백 '똑같은 장면이 2번 나와': 같은 상자 앞면이 첫 장면과 설명 위에 반복됐다.
    # 직접 편집본 1123: 제품 디테일 영상 구간 처음·가운데·끝에서 한 컷씩(앞면 → 연 상자 → 펼친 낱개).
    words = [w(1, ' 먼저 소금우유는 밀크초콜릿이에요.', 10, 13), w(2, ' 겉은 다크초콜릿이고 안에는 캐러멜칩이 들어갔대요.', 14, 18),
             w(3, ' 속에는 소금 우유 크림이 들어가 있어요.', 19, 23), w(4, ' 이건 8점 드릴게요.', 30, 32),
             w(5, ' 다음은 호지차예요.', 40, 42), w(6, ' 이건 6점 드릴게요.', 50, 52)]
    v = asset(words, 60)
    d = asset([], 80, name='디테일.mp4', ident='d')
    d['analysis']['speech'] = []
    def row(i, t, text, tags):
        r = frame(i, t, t + .5, tags, shot=1)
        r['ocr'] = [{'text': text}]
        return r
    detail = [row(i, 1 + .5 * i, '', {'comparison': .3}) for i in range(4)] + \
             [row(100 + i, 10 + .5 * i, '소금우유', {'packaging': .3}) for i in range(60)] + \
             [row(200 + i, 50 + .5 * i, '호지지', {'packaging': .3}) for i in range(8)]
    rules = guided.parse_guideline(default_guideline() + '\n후 나레이션 포함', 'oneshot')
    rules['face_talk'] = False   # 설명 위 디테일 컷 동작 확인(기본은 말할 때 얼굴)
    result = guided.plan([v, d], rules, {'v': [], 'd': detail}, {})
    shown = [(c.get('visual_start', c['start']), c.get('visual_end', c['end'])) for c in result['clips']
             if c.get('visual_asset_id', c['asset_id']) == 'd']
    salt = sorted(a for a, b in shown if 10 <= a < 40)
    assert len(salt) >= 3, shown
    assert all(b - a >= guided.LOOK_GAP for a, b in zip(salt, salt[1:])), salt          # 같은 상자 장면 반복 없음
    assert salt[0] < 18 and salt[-1] > 30, salt                                        # 구간 처음부터 끝까지 고르게
    for i, (a, b) in enumerate(shown):
        assert not any(x < b and y > a for x, y in shown[i + 1:]), shown               # 같은 원본 구간 두 번 없음


def test_eating_moments_pick_the_bite_and_the_show_inside_each_silent_eating_stretch():
    # 사용자 피드백 '먹방 모습이 사라짐': '먹기' 태그가 드물어 먹는 화면이 거의 안 나왔다.
    # 말없이 먹는 구간마다 시각 점수가 가장 높은 한입 순간·단면 보여 주는 순간을 고른다(직접 편집본 246·254초 등).
    v = asset([w(1, ' 먼저 소금우유 먹어볼게요.', 1, 4), w(2, ' 음 짭짤하고 달아요.', 40, 43)], 60)
    rows = []
    for i in range(70):
        t = 4 + .5 * i
        r = frame(i, t, t + .5, {}, shot=1)
        r['similarities'] = {'eating': .2 + (.1 if abs(t - 20) < .3 else 0), 'holding': .2 + (.1 if abs(t - 30) < .3 else 0), 'cream': .2, 'crosssection': .2}
        rows.append(r)
    moments = guided._eating_moments(v, rows)
    centres = sorted(round((m['start'] + m['end']) / 2) for m in moments)
    assert any(abs(c - 20) <= 1 for c in centres) and any(abs(c - 30) <= 1 for c in centres), centres
    kept = [{'kind': 'speech', 'asset_id': 'v', 'start': 40, 'end': 43, 'speech_start': 40, 'labels': ['taste'], 'text': '음 짭짤하고 달아요.'}]
    _, count, _ = guided.overlay_eating(kept, extra=moments)
    assert count == 1 and kept[0]['overlay']['start'] >= 19   # 말 위에 먹방 순간


def test_conti_narration_length_sets_how_long_the_opening_slot_is():
    # 영상 콘티 첫 세 줄(원본에 없는 나레이션) ≈ 10초 → 1.3배속 전 원본 기준 약 12초를 서로 다른 컷으로 채운다.
    words = [w(1, ' 먼저 소금우유는 밀크초콜릿이에요.', 10, 13), w(2, ' 이건 8점 드릴게요.', 20, 22),
             w(3, ' 다음은 호지차예요.', 30, 32), w(4, ' 이건 6점 드릴게요.', 40, 42)]
    v = asset(words, 60)
    d = asset([], 200, name='디테일.mp4', ident='d')
    d['analysis']['speech'] = []
    def row(i, t, text, tags, shot):
        r = frame(i, t, t + 2, tags, shot=shot)
        r['ocr'] = [{'text': text}]
        return r
    detail = [row(i, 2 + 16 * i, '', {'comparison': .3}, i) for i in range(5)] + \
             [row(20 + i, 90 + 2 * i, '소금우유', {'packaging': .3}, 20 + i) for i in range(4)] + \
             [row(30 + i, 120 + 2 * i, '호지지', {'packaging': .3}, 30 + i) for i in range(4)] + \
             [row(40 + i, 140 + 8 * i, '', {'crosssection': .4}, 40 + i) for i in range(6)]
    seconds = {}
    for narration in (None, 9.5):
        rules = guided.parse_guideline(default_guideline() + '\n후 나레이션 포함', 'oneshot')
        if narration:
            rules['narration_seconds'] = narration
        result = guided.plan([v, d], rules, {'v': [], 'd': detail}, {})
        slot = [c for c in result['clips'] if '후 나레이션' in c['guided']['units'][0].get('reason', '')]
        seconds[narration] = sum(c['end'] - c['start'] for c in slot)
        spans = [(c['start'], c['end']) for c in slot]
        assert all(not (a < y and b > x) for i, (a, b) in enumerate(spans) for x, y in spans[i + 1:]), spans
    assert seconds[9.5] > seconds[None] and 10 <= seconds[9.5] <= 13, seconds


def test_talking_always_shows_the_face_and_narration_only_over_eating():
    # 사용자 규칙(2026-11-23): '말할 때는 무조건 화면을 바라봐야 한다고! 먹을 때만 나레이션을 넣어야 한다고!'
    words = [w(1, ' 오늘은 편의점 디저트 두 개를 먹어볼게요.', 1, 4),
             w(2, ' 먼저 소금우유는 밀크초콜릿에 캐러멜칩이 들어갔대요.', 10, 14),
             w(3, ' 단짠단짠해서 맛있네요.', 30, 33),
             w(4, ' 이건 8점 드릴게요.', 40, 42)]
    frames = [frame(1, 10, 14, {}, shot=1), frame(5, 18, 26, {'eating': .4}, shot=5)]
    detail = [frame(10, 5, 6.5, {'packaging': .3}, shot=7), frame(11, 20, 21.5, {'packaging': .3}, shot=8)]
    ev = {('v', frames[0]['id']): [{'name': '소금우유', 'status': 'confirmed'}],
          ('d', detail[1]['id']): [{'name': '소금우유', 'status': 'confirmed'}]}
    # 단, 따로 찍어 끼워 둔 같은 제품 컷은 '제품 설명' 위에는 들어간다(2026-11-23 '내가 중간중간 끼워둔 영상이 아예 없어').
    result, _, _ = two_takes(words, frames, detail, ev, face_talk=True)
    inserted = [c for c in result['clips'] if c['asset_id'] == 'v' and c.get('visual_asset_id', 'v') == 'd']
    assert inserted and all(c['guided']['units'][0]['role'] == 'describe' for c in inserted), inserted
    for c in result['clips']:
        if c['asset_id'] == 'v' and c.get('visual_asset_id', 'v') not in ('v', 'd'):
            raise AssertionError(f'말 위에 다른 원본 화면: {c}')
        if c in inserted:
            continue
        if c['asset_id'] == 'v' and c.get('visual_start') is not None and abs(c['visual_start'] - c['start']) > .05:
            assert 28 <= c['start'] <= 34, c                       # 다른 화면은 맛 평가(먹은 뒤 소감) 위의 먹는 화면뿐
            assert 16 <= c['visual_start'] <= 26, c                # 먹는 장면(18~26초) 근처
    assert guided.parse_guideline(default_guideline(), 'oneshot')['face_talk']


def test_restarted_lines_keep_only_the_last_attempt():
    # 1122 원본 121~144초를 목소리 구간마다 따로 받아 적은 글자. 전체 인식은 '먼저 수유 소금우유는 밀크초콜릿에 … 필링까지'
    # 한 번으로 적었지만 실제로는 네 번 다시 말했다(사용자: '이건 8점, 이건 8점 2번 반복한다니까?').
    bursts = [(121.24, 122.11, '먼저'), (122.13, 123.93, '먼저 씨유소금우유는'), (126.55, 128.06, '밀크초콜릿에 소금을'),
              (130.26, 132.51, '밀크초콜릿에 소금우유 필링까지'), (134.74, 135.13, '네'), (135.25, 136.73, '밀크초콜릿에서 소금을'),
              (138.32, 139.77, '밀크초콜릿에'), (140.21, 141.66, '소금유 필링이랑'), (142.71, 144.41, '캐러멜칩이 들어갔다는데'),
              # 같은 말로 시작하지 않는 다음 문장은 그대로
              (200, 201, '이건 8점 드릴게요'), (202, 203, '이건 진짜 맛있다'), (210, 211, '소금우유는 맛있어요'),
              (212, 213, '소금우유는 8점'), (220, 221, '저는 크런키한'), (222, 223, '저는 개인적으로')]
    found = guided.find_restarts([{'start': a, 'end': b, 'text': t} for a, b, t in bursts])
    assert found == [(121.24, 122.11), (126.55, 128.06), (130.26, 132.51), (135.25, 136.73)]
    # '겉이 닼, 겉이 다크 초콜릿인데': 끊긴 짧은 시도는 인식기가 소리 나는 대로('거치같') 적어도 찾는다
    assert guided.find_restarts([{'start': 397.82, 'end': 398.26, 'text': '거치같'},
                                 {'start': 398.71, 'end': 400.15, 'text': '겉이 다크 초콜릿인데'}]) == [(397.82, 398.26)]
    analysis = {'speech': [[a, b] for a, b, _ in bursts], 'restarts': found}
    assert [a for a, _ in guided.voiced(analysis)][:4] == [122.13, 134.74, 138.32, 140.21]


def test_speech_start_is_pulled_back_when_vad_starts_late():
    # '단짠단짠한데' VAD 324.66초인데 실제 말은 0.4초 먼저 시작('짠한데'로 잘림)
    import numpy as np
    db = np.full(1000, 45., dtype=np.float32)
    db[262:400] = 80.          # 실제 말 2.62초~
    env = {'rate': 100, 'db': db, 'floor': 42., 'voice': 66.}
    assert abs(guided.speech_head(env, 3.0) - 2.57) < .02
    assert guided.speech_head(env, 3.0, lo=2.8) == 2.8                   # 앞 문장 끝을 넘지 않음
    assert guided.speech_head(None, 3.0) == 3.0
    quiet = np.full(1000, 45., dtype=np.float32); quiet[300:] = 80.
    assert guided.speech_head({**env, 'db': quiet}, 3.0) == 3.0           # 이미 맞으면 그대로


def test_line_said_again_without_words_uses_the_last_attempt():
    # 1122 원본 349~353초: '이건 8점 드(멈춤) 이건 8점 드릴게요 / 이거는 8점 드릴게요'. 받아 적힌 건 첫 시도뿐.
    words = [w(1, ' 오늘은 초콜릿을 먹어볼게요.', 300, 303), w(2, ' 단짠단짠해서 맛있네요.', 330, 333),
             {'id': 'x1', 'text': ' 이건', 'start': 349.11, 'end': 349.15, 'confidence': .9},
             {'id': 'x2', 'text': ' 8점', 'start': 349.15, 'end': 350.33, 'confidence': .9},
             {'id': 'x3', 'text': ' 드릴게요.', 'start': 350.33, 'end': 350.87, 'confidence': .9}]
    a = asset(words, 400)
    a['analysis']['speech'] = [[300, 303], [330, 333], [348.98, 349.65], [349.82, 350.78], [351.67, 352.86]]
    a['analysis']['restarts'] = [[348.98, 349.65], [349.82, 350.78]]
    result = guided.plan([a], guided.parse_guideline(default_guideline(), 'oneshot'), {'v': []}, {})
    heard = [(c['start'], c['end']) for c in result['clips'] if c['end'] > 345]
    assert any(s <= 351.7 and e >= 352.8 for s, e in heard), heard          # 끝까지 다시 말한 '이거는 8점 드릴게요'
    assert not any(s < 350.7 and e > 349 for s, e in heard), heard          # 앞 시도는 들리지 않음
    placed = [x for x in timeline.voice_words(a) if x['text'].strip(' .') in ('이건', '8점', '드릴게요')]
    assert all(351.6 <= x['start'] < 352.9 for x in placed), placed           # 자막도 다시 말한 곳에


def test_stumble_at_the_end_of_a_piece_is_cut_and_finished_words_are_not():
    # '저는 크런.. 크런키한 식감이 좋더라구요'(1122 1127.8초): 앞 구간을 빼고 정상으로 말한 뒤만 남긴다
    assert guided.find_restarts([{'start': 1127.77, 'end': 1128.34, 'text': '저는 크리은!'},
                                 {'start': 1128.89, 'end': 1129.76, 'text': '크런키아 식'}]) == [(1127.77, 1128.34)]
    # 앞에 남는 말이 길면 더듬은 끝부분만
    cut = guided.find_restarts([{'start': 10., 'end': 12., 'text': '저는 개인적으로 크런'},
                                {'start': 12.5, 'end': 14., 'text': '크런키한 게 좋아요'}])
    assert len(cut) == 1 and 11.3 < cut[0][0] < 11.8 and cut[0][1] == 12.
    # 말이 끝난 뒤 같은 소리로 시작하는 다음 말은 그대로
    assert guided.find_restarts([{'start': 0., 'end': 1., 'text': '맛있어요'}, {'start': 1.3, 'end': 2., 'text': '요거는 진짜'}]) == []


def test_silence_is_removed_outside_the_opening_narration_slot():
    # 사용자 2026-11-23 '초반 후킹 10초 빼곤 무음 삭제해줘': 문장 안 0.3초 쉼도 자르고, 앞뒤 여유는 말소리가 끝나는 곳까지만
    import numpy as np
    db = np.full(6000, 40., dtype=np.float32)
    for a, b in ((1000, 1150), (1180, 1300), (1400, 1520)):
        db[a:b] = 80.
    words = [{'id': 'a', 'text': ' 먼저', 'start': 10.0, 'end': 11.5, 'confidence': .95},
             {'id': 'b', 'text': ' 소금우유는', 'start': 11.8, 'end': 13.0, 'confidence': .95},
             {'id': 'c', 'text': ' 밀크초콜릿이에요.', 'start': 14.0, 'end': 15.2, 'confidence': .95}]
    a = asset(words, 60)
    a['analysis']['speech'] = [[10.0, 11.5], [11.8, 13.0], [14.0, 15.2]]
    a['_envelope'] = {'rate': 100, 'db': db, 'floor': 40., 'voice': 80.}
    rules = guided.parse_guideline(default_guideline(), 'oneshot')
    assert rules['no_silence'] and not guided.parse_guideline('무음은 남겨줘', 'oneshot')['no_silence']
    clips = guided.plan([a], rules, {'v': []}, {})['clips']
    heard = sum(c['end'] - c['start'] for c in clips if c['asset_id'] == 'v')
    voice = 1.5 + 1.2 + 1.2
    assert heard < voice + .6, clips            # 쉼(0.3초·1초)과 앞뒤 여유가 거의 남지 않음
    assert all(any(c['start'] <= x + .01 and c['end'] >= y - .01 for c in clips) for x, y in ((10, 11.5), (11.8, 13), (14, 15.2)))


def test_word_said_twice_in_one_breath_keeps_one():
    # 사용자 '단어가 중복되면 안돼': 1122 '아니 맛은 맛은 있거든요?'
    words = [(1145.59, 1145.8, ' 아니'), (1145.8, 1146.0, ' 맛은'), (1146.02, 1146.33, ' 맛은'), (1146.36, 1147.2, ' 있거든요?')]
    assert guided.word_repeats(words) == [(1145.8, 1146.02)]
    assert guided.word_repeats([(0, .3, ' 이건'), (.3, .6, ' 8점'), (.7, 1., ' 이건'), (1., 1.3, ' 8점'), (1.3, 1.8, ' 드릴게요')]) == [(0., .7)]
    assert guided.word_repeats([(0, .3, ' 진짜'), (2., 2.3, ' 진짜')]) == []          # 따로 떨어져 말한 건 그대로
    left = guided.voiced({'speech': [[1145.59, 1147.16]], 'restarts': [(1145.8, 1146.02)]})
    assert left == [(1145.59, 1145.8), (1146.02, 1147.16)]                          # '아니'는 남는다
    w0 = [w(1, ' 오늘은 초콜릿을 먹어볼게요.', 1, 3),
          {'id': 'm1', 'text': ' 아니', 'start': 1145.59, 'end': 1145.8, 'confidence': .95},
          {'id': 'm2', 'text': ' 맛은', 'start': 1145.8, 'end': 1146.33, 'confidence': .95},
          {'id': 'm3', 'text': ' 있거든요?', 'start': 1146.36, 'end': 1147.16, 'confidence': .95}]
    a = asset(w0, 1200)
    a['analysis']['speech'] = [[1, 3], [1145.59, 1147.16]]
    a['analysis']['restarts'] = [(1145.8, 1146.02)]
    clips = guided.plan([a], guided.parse_guideline(default_guideline(), 'oneshot'), {'v': []}, {})['clips']
    heard = [(c['start'], c['end']) for c in clips if c['end'] > 1100]
    assert heard and not any(s < 1146.0 and e > 1145.82 for s, e in heard), heard   # 앞의 '맛은'은 들리지 않음


def test_product_name_joined_by_symbol_stays_one_word():
    # 1122: 콘티로 고친 '허니&페어인데'가 '허니'·'페어'로 갈라져 '필링이랑'이 제품 이름이 됐고, 허니페어 상자 컷이 하나도 안 들어갔다.
    assert guided._name_tokens('이마트24도 허니&페어인데') == ['허니페어']
