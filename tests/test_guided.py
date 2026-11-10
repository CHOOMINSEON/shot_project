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
    return guided.DEFAULT_GUIDELINE


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
    assert rules['target'] == (45, 60)
    assert rules['frame'] == 'auto'            # '제품 클로즈업'을 전체 크롭으로 오판하지 않음
    assert {'packaging', 'opening', 'cutting', 'crosssection', 'eating', 'conclusion'} <= rules['keep']
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
    assert any(c['start'] <= 13 and c['end'] >= 16 for c in result['clips'])
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
    for i in range(30):
        words.append(w(i, f' 일반 이야기 {i}번째 문장이에요.', t, t + 2))
        t += 3
    words.append(w(99, ' 결론은 다시 사 먹고 싶어요.', t, t + 2))
    result, _, a = run(words, duration=t + 5)
    assert result['seconds'] <= 60
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
