"""자막 줄 단위로 끊어 쓴 대본(오디세이 해석 영상)을 문장으로 묶어 찾고, 대본 그대로 자막을 만드는지 확인한다."""
import random

from studio import script_edit

SCRIPT = """20년 만에
돌아온 집을
왜 다시
떠났을까요?
오디세이
결말에는
찜찜한 질문이
남습니다.
오디세우스에게
트로이 목마는
승리의 상징이지만
그 승리 뒤에는
수많은
죽음이 있었고,
돌아오는 길에도
그 기억이
따라붙습니다.
여러분은
이 마지막 여정이
진짜 해피엔딩으로
보이시나요?"""


def words_for(sentence, start, conf=.95, pace=.28):
    out, t = [], start
    for k, token in enumerate(sentence.split()):
        out.append({'id': f'{start}-{k}', 'text': (' ' if k else ' ') + token, 'start': round(t, 2), 'end': round(t + pace, 2), 'confidence': conf})
        t += pace + .02
    return out, t


def raw_footage():
    """촬영 원본 흉내: 문장마다 여러 번 말하기(앞부분 끊김·군말·뭉개짐 섞임), 문장 사이 긴 정적."""
    sentences = ['20년 만에 돌아온 집을 왜 다시 떠났을까요?', '오디세이 결말에는 찜찜한 질문이 남습니다.',
                 '오디세우스에게 트로이 목마는 승리의 상징이지만 그 승리 뒤에는 수많은 죽음이 있었고, 돌아오는 길에도 그 기억이 따라붙습니다.', '여러분은 이 마지막 여정이 진짜 해피엔딩으로 보이시나요?']
    words, t, best_starts = [], 2., []
    for k, sentence in enumerate(sentences):
        tokens = sentence.split()
        attempts = [(' '.join(tokens[:3]), .9), (' '.join(tokens[:2] + ['음'] + tokens[2:]), .8), (sentence, .55), (sentence, .97), (sentence, .85)]
        for text, conf in attempts:
            if text == sentence and conf == .97:
                best_starts.append(t)
            chunk, t = words_for(text, t, conf)
            words += chunk
            t += 1.5
    return words, best_starts


def asset(words, duration=120):
    return {'id': 'v', 'name': '원본.mp4', 'status': 'ready', 'metadata': {'duration': duration, 'has_audio': True, 'has_video': True},
            'analysis': {'transcribed': True, 'words': words}}


def test_group_lines_into_sentences_only_for_chunked_scripts():
    lines = list(enumerate(SCRIPT.splitlines()))
    groups = script_edit.group_lines(lines)
    assert [len(g[0]) for g in groups] == [4, 4, 9, 4]
    assert groups[0][1] == ['20년 만에', '돌아온 집을', '왜 다시', '떠났을까요?']
    plain = [(0, '아니 제가 CU 다섯 곳이나 돌아서 겨우 3개 구했거든요?'), (1, '과연 찾아다닐 만큼 맛있을까?')]
    assert [len(g[0]) for g in script_edit.group_lines(plain)] == [1, 1]
    placeholder = [(0, '네'), (1, '[첫 번째 제품명·실제 맛 평가]이고,'), (2, '그래요.')]
    assert all(len(g[0]) == 1 for g in script_edit.group_lines(placeholder))


def test_chunked_script_matches_best_take_and_builds_script_captions():
    words, best = raw_footage()
    state = {'clips': [], 'protections': [], 'fps': 30, 'captions': {'items': []}}
    value = script_edit.assemble(script_edit.Brief(script=SCRIPT), state, {'v': asset(words)})
    report = value['script_edit']['lines']
    assert value['script_edit']['complete'], [(r['script'], r['status']) for r in report]
    # 5번 말한 문장마다 가장 또렷한(신뢰도 .97) 테이크가 선택된다
    starts = sorted(r['start'] for r in report)
    for chosen, expected in zip(starts, best):
        assert abs(chosen - expected) < .6, (chosen, expected)
    assert all(r.get('takes', 1) >= 2 for r in report)
    # 자막: 대본 줄 그대로, 순서·시간 정상
    items = value['captions']['items']
    assert [c['text'] for c in items] == SCRIPT.splitlines()
    assert all(a['end'] <= b['start'] + 1e-6 for a, b in zip(items, items[1:]))
    assert all(0 <= c['start'] < c['end'] <= sum(k['end'] - k['start'] for k in value['clips']) + .01 for c in items)
    assert not any(c['review_reasons'] for c in items)   # 신뢰도 높은 테이크라 검수 경고 없음
    assert items[0]['source_text'].replace(' ', '').startswith('20년')
    # 줄이 같은 문장 안에서 시간순으로 이어진다
    first_sentence = items[:4]
    assert first_sentence[0]['start'] < first_sentence[1]['start'] < first_sentence[2]['start'] < first_sentence[3]['start']


def test_missing_sentence_stays_missing():
    words, _ = raw_footage()
    words = [w for w in words if '해피엔딩' not in w['text'] and '여러분은' not in w['text']]
    state = {'clips': [], 'protections': [], 'fps': 30, 'captions': {'items': []}}
    value = script_edit.assemble(script_edit.Brief(script=SCRIPT), state, {'v': asset(words)})
    statuses = {tuple(r.get('lines', [r['line']])): r['status'] for r in value['script_edit']['lines']}
    assert statuses[(18, 19, 20, 21)] == 'missing'
    assert not value['script_edit']['complete']
    assert all('해피엔딩' not in c['text'] for c in value['captions']['items'])
