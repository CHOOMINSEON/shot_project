"""영상 콘티(대본) 활용: 1122 가나 프리미엄 콘티와 원본 인식 결과(사용자 피드백 2026-11-23 '콘티에도 적혀 있을텐데 대사 참고 안해?')."""
from studio import conti, guided, timeline

STORY = '''이거 구하려고 무려 일주일이 걸린 고오급 초콜릿?
편의점마다 파는 맛이 달라서 집 근처 편의점은 거의 다 돌아다닌 것 같은데, 특히 GS25랑 이마트24 거 구하기가 유독 힘들었어요.
패키지부터 고급스럽긴 한데 한 상자에 4,800원이라 쪼끔 비싸게 느껴졌고, 이 가격에 다시 살 맛이 있는지 먹어봤습니다.
세븐일레븐 크림브륄레는 커스터드 크림에 캐러멜 칩이 들어갔는데, [커스터드 맛과 칩 식감에 대한 실제 반응].
CU 소금우유도 캐러멜 칩이 들어갔는데, 크림브륄레랑 바로 비교해보니까 [짠맛이 느껴지는 정도와 두 맛의 실제 차이].
GS25 호지차부터는 겉이 다크 초콜릿인데, [다크 초콜릿 사이로 호지차 향이 얼마나 느껴지는지 실제 반응].
이마트24 허니&페어는 꿀맛 필링에 배 시럽까지 넣었다는데, [꿀맛과 배 향 중 뭐가 먼저 느껴졌는지 실제 반응].
4,800원 주고 다시 산다면 [제품명과 이유 또는 재구매하지 않을 이유].
여러분이라면 딱 하나만 뭐 고르실래요?'''

# 1122 원본(011802) 실제 인식 결과에서 고른 단어들
SPOKEN = [' 먼저', ' 수유', ' 소금우유는', ' 밀크초콜릿에', ' 소금우유', ' 필링까지', ' 캐러멜칩이', ' 들어갔다는데', ' 모양은',
          ' GS호지차부터는', ' 거치', ' 다크', ' 초콜릿인데', ' 호주차', ' 향이', ' 이마트24도', ' 허니페어인데', ' 안에는', ' 꿀맛',
          ' 필링이랑', ' 배시럽이', ' 들어갔습니다.', ' 마지막은', ' 세븐일레븐의', ' 빌렐레인데', ' 다크초콜릿', ' 코팅에',
          ' 미약하게', ' 크림브렐레', ' 맛이', ' 나요.', ' 이렇게', ' 네', ' 가지를', ' 다', ' 먹어봤는데', ' 수유가', ' 맛있다.']


def words():
    return [{'id': f'w{i}', 'start': i * .5, 'end': i * .5 + .4, 'text': t} for i, t in enumerate(SPOKEN)]


def test_conti_names_fix_misheard_store_and_product_names_and_keep_the_rest():
    found = conti.names(STORY)
    assert found['pairs'] == [('세븐일레븐', '크림브륄레'), ('CU', '소금우유'), ('GS25', '호지차'), ('이마트24', '허니&페어')]
    out = conti.correct_words(words(), STORY)
    changed = {w['asr_text']: w['text'] for w in out if w.get('asr_text')}
    assert changed == {' 수유': ' CU', ' 호주차': ' 호지차', ' 허니페어인데': ' 허니&페어인데',
                       ' 빌렐레인데': ' 크림브륄레인데', ' 크림브렐레': ' 크림브륄레'}
    # 콘티 이름과 관계없는 말은 그대로('수유가'는 제품 이름 앞이 아니다)
    assert [w['text'] for w in out if not w.get('asr_text')] == [t for t in SPOKEN if t not in changed]
    assert conti.correct_words(words(), '') == words()


def test_leading_conti_lines_missing_from_the_source_are_post_narration_about_ten_seconds():
    said, seconds = conti.narration_lines(STORY, words())
    assert len(said) == 3 and said[0].startswith('이거 구하려고') and said[2].startswith('패키지부터')
    assert 8 <= seconds <= 12   # 사용자: '초반 10초 나레이션 영상 없긴 해'
    # 콘티가 원본에서 말한 줄로 시작하면 나레이션 자리가 없다
    assert conti.narration_lines('먼저 수유 소금우유는 밀크초콜릿에 소금우유 필링까지\n' + STORY, words())[0] == []


def test_real_reaction_hints_belong_to_the_product_of_their_line():
    found = conti.hints(STORY)
    assert '짠맛' in found['소금우유'] and '짠맛' not in found['크림브륄레']
    assert {'꿀', '배'} <= set(found['허니&페어'])
    assert '향' in found['호지차'] and '재구매하지' in found['__재구매__']
    assert not any(b in ws for ws in found.values() for b in ('이마트', 'CU', '세븐일레븐', '소금우유'))


def test_captions_use_conti_names():
    clip = {'id': 'c1', 'asset_id': 'a', 'start': 0., 'end': len(SPOKEN) * .5, 'track': 'main'}
    asset = {'id': 'a', 'metadata': {'duration': 30, 'has_video': True}, 'analysis': {'words': words(), 'speech': []}}
    caps = timeline.generate_captions({'clips': [clip], 'storyboard': STORY}, {'a': asset})['items']
    text = ' '.join(c['text'] for c in caps)
    assert 'CU 소금우유는' in text and '크림브륄레인데' in text and '호지차' in text
    assert '수유 소금' not in text and '빌렐레' not in text and '호주차' not in text
