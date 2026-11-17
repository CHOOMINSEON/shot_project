"""편집 지침 기반 자동 편집 (규칙 기반, LLM 불필요).

입력: 실제 발화 단어(시간 포함), 프레임 장면 인덱스, 제품 근거, 편집 지침, 영상 유형.
출력: 타임라인 구간(clips) + 구간별 근거·삭제 이유·확인 필요 목록.

원칙
- 실제로 말하지 않은 평가·결론은 만들지 않고, 없으면 `missing`에 적는다.
- 표정·음식 화면만으로 맛·재구매를 판단하지 않는다. 평가는 실제 발화로만 분류한다.
- 숫자·부정 표현이 다른 문장은 '반복'으로 보지 않는다.
- 문장 중간은 자르지 않는다. 목표 길이를 못 맞추면 경고하고 그대로 둔다.
이 모듈은 FastAPI/모델 없이 순수 Python으로 동작한다(테스트 가능).
"""
import difflib
import math
import re

# 기본 편집 지침(사용자가 화면에서 수정 가능). 실행 파일에 함께 들어가도록 코드에 포함한다.
DEFAULT_GUIDELINE = """업로드한 영상에서 중요한 부분을 골라 세로 9:16 숏폼으로 편집해줘.

목표 길이는 30~90초로 하되, 중요한 평가나 발언, 문장 끝을 자르면서 억지로 길이를 맞추지 마. 내용이 짧으면 짧은 대로 두고, 길이를 채우려고 의미 없는 장면을 넣지 마.

먼저 영상을 보고 무엇을 다루는 영상인지(제품 리뷰, 음식 시식, 행사·장소 방문, 브이로그, 정보 설명 등) 파악한 뒤 그에 맞게 편집해줘.

남길 장면:
- 영상의 핵심 질문이나 가장 강한 반응·평가가 담긴 장면 (첫 장면 후보)
- 다루는 대상(제품, 음식, 장소, 사람, 무대)이 잘 보이는 장면과 이름·포장·간판이 읽히는 장면
- 대상을 실제로 써보거나 먹거나 체험하는 순간
- 체험 직후 맛, 식감, 사용감, 분위기를 구체적으로 말하는 발화
- 가격, 장점, 아쉬운 점, 비교를 설명하는 구간
- 현장에서 다른 사람이 한 말이나 웃긴 상황 (현장음 그대로)
- 실제로 말한 최종 결론, 추천, 재구매·재방문 의사, 댓글 질문

줄일 부분:
- 촬영 준비, 카메라 조정, 의미 없는 대기, 이동
- 불필요하게 반복한 설명, 같은 동작이나 시식의 반복 (가장 반응이 분명한 한 번만 남기기)
- 말실수 후 다시 말한 경우 앞의 실패한 부분
- 장면 설명에 필요하지 않은 긴 무음
- 길이가 넘치면 포장 뜯기, 전경, 입장, 이동 장면부터 줄이기

단, 클로즈업, 단면, 개봉, 결과 공개, 시식·체험 순간, 무대 장면은 음성이 없다는 이유만으로 삭제하지 마.

구성:
- 실제 영상에 있는 핵심 질문, 강한 반응이나 가장 눈에 띄는 화면으로 시작
- 소개 → 보여주기(개봉·내용물·현장) → 체험 → 평가 → 결론 순서
- 여러 제품·장소·행사는 대상별로 묶고, 서로 다른 대상의 설명과 화면을 섞지 마.
- 실제로 일어난 순서가 이야기의 일부이거나 순서를 바꾸면 발언 의미가 달라지는 경우 원래 순서를 유지
- 마지막은 결론이나 댓글 질문으로 끝내기

자막·표기:
- 자막은 영상에서 실제로 말한 내용 그대로, 한 화면에 짧게 끊어서 달기. 현장음 발언에도 자막 달기.
- 다루는 대상이 처음 나올 때 이름 표시
- 영상 안에서 광고·협찬을 언급하면 화면 상단에 '유료광고 포함'을 처음부터 끝까지 표시

함께 준 대본이나 기획안이 있으면 참고용으로만 써줘. 실제 촬영에서 말한 내용과 단어나 순서가 다를 수 있으니 똑같은 문장을 찾지 말고 같은 뜻의 실제 발화를 찾고, 컷과 자막은 실제로 말한 내용을 기준으로 해줘. 대본에 있는 장면이 원본에 없으면 비슷한 장면으로 대신하지 말고 없다고 알려줘.

실제로 말하지 않은 평가나 결론은 만들지 마. 반응이 불분명하거나 근거가 부족하면 '확인 필요'로 표시하고, 먼저 추천 편집본을 만들어 내가 확인할 수 있게 해줘.

이번 영상 정보 (있는 것만 채우고 나머지는 지워도 됨):
- 영상 주제:
- 첫 장면으로 쓰고 싶은 장면이나 강조 자막:
- 꼭 넣을 장면:
- 촬영하지 않은 장면 (찾지 말 것):
- 현장음을 살릴 구간:
- 광고·협찬 여부:
- 참고 대본:"""

DEFAULT_GUIDELINE_COMMENTARY = """업로드한 영화·TV·애니메이션 해석 영상에서 핵심 주장과 근거만 골라 세로 9:16 숏폼으로 편집해줘.

목표 길이는 45~60초로 하되, 주장이나 문장 끝을 자르면서 억지로 길이를 맞추지 마.

남길 장면:
- 영상 처음의 질문이나 핵심 주장
- 작품 속 장면을 근거로 설명하는 발화
- 내 해석이나 이유를 말하는 구간
- 시청자에게 던지는 마지막 질문이나 결론

줄일 부분:
- 촬영 준비, 카메라 조정, 의미 없는 대기
- 불필요하게 반복한 설명
- 말실수 후 다시 말한 경우 앞의 실패한 부분
- 장면 설명에 필요하지 않은 긴 무음

구성:
- 질문으로 시작 → 근거 장면과 설명 → 해석 → 시청자에게 질문 순서
- 순서를 바꾸면 말의 의미가 달라지는 경우 원래 맥락 유지

실제로 말하지 않은 해석이나 결론은 만들지 말고, 먼저 추천 편집본을 만들어 내가 확인할 수 있게 해줘."""

GUIDELINES = {'default': DEFAULT_GUIDELINE, 'commentary': DEFAULT_GUIDELINE_COMMENTARY}

# ---------------------------------------------------------------- 영상 유형(5종 + 해석 리뷰)
# 사용자가 설명한 5가지 제작 방식. 값은 시작점이며 지침·프로필이 덮어쓴다.
STYLES = {
    'oneshot': {
        'name': '원테이크 먹방 리뷰', 'target': (45, 60), 'hook': 'speech', 'narration': False,
        'max_silent_visual': 5.0, 'max_shot': None, 'frame': 'auto',
        'order': ['intro', 'opening', 'eating', 'taste', 'conclusion'],
        'note': '촬영 순서를 유지하고 준비·말실수·반복·긴 무음만 줄입니다.'},
    'cook_mukbang': {
        'name': '조리 짧은 컷 + 먹방 (나레이션 후녹음)', 'target': (55, 75), 'hook': 'visual', 'narration': True,
        'max_silent_visual': 3.0, 'max_shot': 4.0, 'frame': 'auto',
        'order': ['cooking', 'eating', 'taste', 'conclusion'],
        'note': '조리 컷은 짧게, 먹방은 1~2개. 나레이션은 따로 연결합니다.'},
    'recipe': {
        'name': '레시피 (얼굴 후킹 + 조리 + 나레이션)', 'target': (22, 70), 'hook': 'visual', 'narration': True,
        'max_silent_visual': 3.0, 'max_shot': 4.0, 'frame': 'auto',
        'order': ['eating', 'cooking', 'eating'],
        'note': '완성 장면/얼굴 후킹으로 시작하고 조리 컷을 순서대로 잇습니다.'},
    'vlog': {
        'name': '브이로그 (짧은 컷 + 나레이션)', 'target': (20, 45), 'hook': 'visual', 'narration': True,
        'max_silent_visual': 2.5, 'max_shot': 3.0, 'frame': 'auto',
        'order': [], 'note': '먹는 장면이 없어도 됩니다. 컷은 짧게 유지합니다.'},
    # 채널 '이요저장소'(영화·TV·애니 해석) 쇼츠 1개(60초)에서 파악: 얼굴로 말하는 영상 + 작품 장면 겹침, 4구간(12/18/14/16초),
    # 질문형 제목, 마지막에 시청자 질문. 작품 장면 자동 인식은 아직 없어 장면 연결은 직접 합니다.
    'commentary': {
        'name': '영화·TV·애니 해석 리뷰 (말하는 영상 + 작품 장면)', 'target': (45, 65), 'hook': 'speech', 'narration': False,
        'max_silent_visual': 3.0, 'max_shot': None, 'frame': 'auto',
        'order': [], 'note': '말하는 흐름(질문→근거→해석→시청자 질문)을 유지하고 말실수·반복·무음만 줄입니다. 작품 장면은 직접 연결합니다.'},
    'restaurant': {
        'name': '맛집 리뷰 (짧은 컷 + 먹방 + 나레이션)', 'target': (22, 55), 'hook': 'visual', 'narration': True,
        'max_silent_visual': 3.0, 'max_shot': 4.0, 'frame': 'auto',
        'order': ['packaging', 'cooking', 'eating', 'taste', 'conclusion'],
        'note': '가게·메뉴·음식·먹방 컷 위주. 나레이션은 따로 연결합니다.'},
}

# 업로드한 완성본 6개(2026-10~11월, 21~70초)를 측정한 값. 평균 컷 0.9~1.3초(중앙값 0.8~1.1초), 분당 46~66컷,
# 컷이 가장 길었던 곳은 먹는 장면(최대 7.7초). 자막은 화면 가운데, 흰 글씨+검은 외곽선, 2~5단어씩 끊어 표시.
# 표본이 적어(스타일당 1개 안팎) 시작값으로만 쓰고, 지침·사용자 수정이 우선한다.
# 2026-11 완성본 1116(GS25 신상 5종, 69.4초) 실측: 컷 52개(분당 약 45컷, 평균 1.3초), 후킹 4초 안에 전체샷·포장·한입·단면 4컷,
# 제품별 블록 8~15초(포장 들어 보이기 → 고른 이유 → 개봉·단면 → 한입 → 짧은 반응 여러 개 → 가격 불만 → "N점 드릴게요"),
# 마지막 3초에 1위 제품과 댓글 질문. 대본의 [실제 반응] 자리는 대본에 없는 즉흥 발화로 채워져 있다.
# 원본(35분 28초)과 소리 대조로 확인한 값: 전체 1.4배속, 원본에서 쓴 분량 90초(4.2%), 소리 컷 60개(원본 기준 중앙값 1.3초),
# 첫 4초 후킹은 촬영 맨 앞(70초·113초 지점)에서 가져오고 그 뒤는 전부 촬영 순서 그대로. 한 제품에서 여러 번 말한 구간(예: 86초 분량)에서 11초만 남김.
CHANNEL_STYLE = {'multi_product': {'speed': 1.4, 'source_kept_ratio': 0.042, 'audio_cuts': 60, 'median_source_cut': 1.33, 'order': 'chronological',
                                   'hook_seconds': 4, 'hook_shots': 4, 'block_seconds': (8, 15), 'block_end': 'score',
                                   'outro_seconds': 3, 'total_seconds': 69, 'cuts': 52},
                 'median_cut': 0.9, 'cuts_per_minute': (46, 66), 'loudness_lufs': (-10.4, -8.1),
                 'caption': {'position': 'center', 'words_per_caption': (2, 5), 'font': 'bold white, black outline'},
                 'structure': ['hook(face or food close-up)', 'cooking/unboxing close-ups', 'eating with face', 'verdict/question to camera']}

# 장면 역할 우선순위(한 프레임에 여러 태그가 있을 때)
VISUAL_ROLES = ['eating', 'crosssection', 'cutting', 'opening', 'cooking', 'packaging']
# '음식이 보인다'는 이유만으로 보존하지 않는다 → product_full·closeup·holding·reaction 제외
PROTECT_ROLES = set(VISUAL_ROLES)
ROLE_LABEL = {'eating': '시식', 'crosssection': '단면·내용물', 'cutting': '자르기', 'opening': '개봉',
              'cooking': '조리', 'packaging': '제품·포장'}

# ------------------------------------------------------------------ 지침 해석
KEEP_WORDS = [('packaging', r'포장|제품명|패키지|간판|이름'), ('opening', r'개봉'), ('cutting', r'자르'),
              ('crosssection', r'단면|내용물'), ('eating', r'먹는|먹거나|시식 장면|체험하는|써보'),
              ('taste', r'맛|식감|사용감'), ('price', r'가격'), ('pro', r'장점'), ('con', r'아쉬운|단점'),
              ('conclusion', r'결론|재구매|재방문|추천'), ('cooking', r'조리|만드는')]
DROP_WORDS = [('prep', r'준비|카메라'), ('repeat', r'반복'), ('retake', r'말실수'), ('silence', r'무음|대기')]
ORDER_WORDS = [('intro', r'제품 소개|소개'), ('opening', r'개봉'), ('crosssection', r'내용물|단면'),
               ('eating', r'시식|먹|체험'), ('taste', r'평가'), ('conclusion', r'결론')]
UNSUPPORTED = ['음악', '효과음', '전환 효과', '얼굴 추적', '줌인', '자막 스타일', '속도', '배속']


def parse_guideline(text, style='oneshot'):
    """지침 문장 → 구조화 규칙. 해석하지 못한 항목은 `unapplied`에 남긴다."""
    base = STYLES.get(style, STYLES['oneshot'])
    text = text or ''
    rules = {'style': style, 'target': tuple(base['target']), 'keep': set(), 'drop': set(), 'order': [],
             'hook': base['hook'], 'protect_silent': True, 'group_products': False,
             'keep_context': True, 'fast': False, 'frame': base['frame'], 'applied': [], 'unapplied': []}
    section = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        head = re.match(r'^(남길 장면|줄일 부분|구성)\s*:', line)
        if head:
            section = {'남길 장면': 'keep', '줄일 부분': 'drop', '구성': 'order'}[head[1]]
            continue
        if re.search(r'삭제하지\s*마', line):
            # '단, 단면·개봉·시식은 … 삭제하지 마' 줄은 줄일 부분이 아니라 보존 목록이다.
            rules['keep'] |= {k for k, p in KEEP_WORDS + [('eating', r'시식|체험')] if re.search(p, line)}
            continue
        if section == 'keep':
            rules['keep'] |= {k for k, p in KEEP_WORDS if re.search(p, line)}
        elif section == 'drop':
            rules['drop'] |= {k for k, p in DROP_WORDS if re.search(p, line)}
        elif section == 'order' and '→' in line:
            order = [k for part in re.split(r'→', line.split(':')[-1] if ':' in line else line)
                     for k, p in ORDER_WORDS if re.search(p, part)]
            rules['order'] = list(dict.fromkeys(order))
    m = re.search(r'(\d+)\s*[~\-–]\s*(\d+)\s*초', text)
    if m and int(m[1]) < int(m[2]):
        rules['target'] = (int(m[1]), int(m[2]))
        rules['applied'].append(f'목표 길이 {m[1]}~{m[2]}초')
    elif (m := re.search(r'(\d+)\s*초', text)) and 5 <= int(m[1]) <= 600:
        rules['target'] = (max(5, int(int(m[1]) * .85)), int(m[1]))
        rules['applied'].append(f'목표 길이 약 {m[1]}초')
    if re.search(r'(핵심 질문|핵심 평가|질문이나 평가).*시작|평가로 시작', text):
        rules['hook'] = 'speech'
        rules['applied'].append('실제 발화의 핵심 질문·평가로 시작')
    if re.search(r'제품별|대상별', text):
        rules['group_products'] = True
        rules['applied'].append('제품별로 묶기')
    if re.search(r'음성이 없다는 이유만으로\s*삭제하지|무음.*삭제하지', text):
        rules['applied'].append('음성 없는 개봉·단면·시식·제품 장면 보존')
    if re.search(r'빠르|템포|타이트', text):
        rules['fast'] = True
        rules['applied'].append('빠른 템포(말 앞뒤 여유 축소)')
    if '흐린 배경' in text:
        rules['frame'] = 'blur'
        rules['applied'].append('9:16 흐린 배경 채우기')
    elif re.search(r'중앙\s*크롭|화면\s*채우기', text):
        rules['frame'] = 'fill'
        rules['applied'].append('9:16 중앙 크롭')
    # '제품 클로즈업'은 보존할 장면이지 화면 확대 지시가 아니다(이전 버전 오판 수정).
    if not rules['keep']:
        rules['keep'] = {k for k, _ in KEEP_WORDS}
    # 영상 유형이 필요로 하는 장면 역할은 지침에 없어도 기본 보존(예: 레시피의 조리 컷)
    rules['keep'] |= {r for r in base['order'] if r in PROTECT_ROLES}
    if not rules['drop']:
        rules['drop'] = {k for k, _ in DROP_WORDS}
    if rules['order']:
        rules['applied'].append('구성 순서 ' + ' → '.join(rules['order']))
    for word in UNSUPPORTED:
        if word in text:
            rules['unapplied'].append(f'{word}: 자동 적용하지 않음')
    rules['applied'] += ['준비·재촬영·반복·긴 무음 줄이기', '문장 끝 보존(말끝 여유 0.2~0.35초)']
    # 먹방·시식형에서만 쓰는 연출(완성본 1116에서 배운 것). 해석·브이로그 영상에는 적용하지 않는다.
    food = style in ('oneshot', 'cook_mukbang', 'restaurant')
    rules['overlay_eating'] = food and not re.search(r'평가\s*소리.*얹지\s*마|화면\s*바꾸지\s*마', text)
    rules['hook_montage'] = (food or style == 'recipe') and not re.search(r'몽타주\s*(빼|없이|쓰지)', text)
    if rules['overlay_eating']:
        rules['applied'].append('맛 평가 소리 위에 직전의 먹는·단면 화면 얹기')
    if rules['hook_montage']:
        rules['applied'].append('후킹 멘트 아래 제품 장면 빠른 컷(0.28초씩)')
    return rules


# ------------------------------------------------------------ 발화 분석(규칙)
def norm(text):
    return ''.join(c for c in str(text).lower() if c.isalnum())


def critical_equal(a, b):
    """숫자·부정이 다르면 같은 주장으로 보지 않는다."""
    return (re.findall(r'\d+', a) == re.findall(r'\d+', b)
            and all((t in a) == (t in b) for t in ['못', '않', '없', '아니', '안']))


TASTE = r'맛있|맛없|맛이|달[아고다콤]|달달|짜[다요서고]|짭|싱거|고소|느끼|매콤|맵[다고지]|쫄깃|바삭|촉촉|부드럽|쫀득|눅눅|퍽퍽|꾸덕|진하|담백|새콤|쓰[다고]|비리|단짠|풍미|식감|향이|냄새'
CLASSIFIERS = [
    # 제품별 마무리 점수("8점 드릴게요"): 실제 완성본(1116)에서 제품마다 이 한마디로 끝난다 → 길이를 줄여도 남긴다.
    ('score', r'(\d+|[한두세네]|다섯|여섯|일곱|여덟|아홉|열|[일이삼사오육칠팔구십])\s*점\s*(드릴|줄게|줄\s*게|드려|드립|입니다|이에요|정도|만점)|\d+\s*점[.!…~]*\s*$|점\s*만점'),
    ('repurchase', r'재구매|다시\s*(사|먹|만들)|또\s*(사|먹|만들)|사\s*먹고\s*싶|사먹을|만들어\s*먹을'),
    ('conclusion', r'결론|총평|한\s*줄\s*평|추천(해|드|합)|비추|살\s*만|사\s*볼\s*만|돈\s*아깝|아깝지'),
    ('price', r'\d[\d,]*\s*원|가격|가성비|천\s*원|만\s*원|할인|행사|1\s*\+\s*1|2\s*\+\s*1'),
    ('taste', TASTE),
    ('con', r'아쉽|아쉬운|아쉬워|아쉬웠|단점|별로|부족|비싸|적어|양이\s*적|작아|실망'),
    ('pro', r'장점|좋[네은았아]|괜찮|만족|넉넉|푸짐|가득'),
    ('conclusion', r'여러분은?.*(보셨|생각|어떠|어땠)|(어떻게|어떤)\s*(보|느끼|생각)'),   # 시청자에게 묻는 마무리 질문
    ('question', r'\?|까요|나요|할까|일까|인가요|궁금|왜\s'),
    ('cooking', r'넣[고어은]|붓|돌려|돌리|섞|끓|굽|볶|올려|올리|자르|뿌리|익히|부수|전자레인지|\d+\s*분'),
    ('intro', r'오늘은|이번에|소개|신상|편의점|출시|나왔|새로\s*나|이\s*제품|제품은'),
]
MISTAKE = re.compile(r'(다시\s*(할게|해볼게|갈게|찍)|잠깐|엔지|NG|아\s*잘못|컷|레디|카메라|촬영\s*(시작|준비)|녹화)', re.I)


def classify(text):
    """문장 분류. 평가 극성은 판단하지 않고, 부정·숫자 표시만 남긴다."""
    labels = [name for name, pattern in CLASSIFIERS if re.search(pattern, text)]
    negated = bool(re.search(r'(?<![가-힣])안\s*[가-힣]|못|않|없|아니|별로', text))
    complete = bool(re.search(r'(다|요|죠|까|네|해|임|음|니다|[.?!。…])\s*$', text.strip()))
    return {'labels': labels, 'negated': negated, 'complete': complete,
            'numbers': re.findall(r'\d[\d,]*', text),
            'mistake': bool(MISTAKE.search(text)), 'texture': bool(re.search(r'쫄깃|바삭|촉촉|부드럽|쫀득|눅눅|퍽퍽|꾸덕|식감', text))}


def split_restarts(bucket):
    """같은 문장 안에서 앞부분을 다시 말한 경우(말실수 재시도)를 둘로 나눈다.

    예: "이거 식감이 쫄깃 이거 식감이 쫄깃하고 촉촉해서" → ["이거 식감이 쫄깃", "이거 식감이 쫄깃하고 촉촉해서"]
    앞 조각이 뒤 조각의 시작과 같아야 하며 4글자 이상일 때만 나눈다.
    """
    for i in range(2, len(bucket) - 1):
        head = norm(''.join(w['text'] for w in bucket[:i]))
        tail = norm(''.join(w['text'] for w in bucket[i:]))
        if len(head) >= 4 and len(tail) > len(head) and tail.startswith(head):
            return [bucket[:i]] + split_restarts(bucket[i:])
    return [list(bucket)]


FILLER = re.compile(r'^(음+|어+|으+|아+|그+|저+|엄+|흠+)[.,…~]*$')


def take_quality(part):
    """한 번 말한 문장(테이크)이 얼마나 또렷한지 점수화(0~1 근처). 내용의 좋고 나쁨은 평가하지 않는다.

    음성 인식 신뢰도(발음이 뭉개지면 낮아짐), 가장 낮은 단어, 군말·같은 단어 연속 반복(더듬음),
    문장 중간의 긴 멈춤, 말 속도가 정상 범위를 벗어난 정도를 본다.
    """
    confs = [float(w.get('confidence', 0)) for w in part] or [0.]
    tokens = [norm(w['text']) for w in part]
    fillers = sum(1 for w in part if FILLER.match(w['text'].strip()))
    stutters = sum(1 for a, b in zip(tokens, tokens[1:]) if a and a == b)
    gaps = sum(1 for a, b in zip(part, part[1:]) if float(b['start']) - float(a['end']) > .45)
    seconds = max(.2, float(part[-1]['end']) - float(part[0]['start']))
    rate = len(norm(''.join(w['text'] for w in part))) / seconds
    rate_penalty = .0 if 3. <= rate <= 10. else min(.2, abs(rate - (3. if rate < 3. else 10.)) * .03)
    score = .55 * (sum(confs) / len(confs)) + .25 * min(confs) - .08 * fillers - .08 * stutters - .05 * gaps - rate_penalty
    notes = []
    if fillers:
        notes.append(f'군말 {fillers}')
    if stutters:
        notes.append(f'더듬음 {stutters}')
    if gaps:
        notes.append(f'문장 중 멈춤 {gaps}')
    if min(confs) < .5:
        notes.append('뭉개진 발음 의심')
    return round(score, 3), notes


def split_sentences(words, duration, gap=.7, longest=12.):
    """단어(시간 포함) → 문장. 문장 경계는 구두점·무음 간격. 말 도중 재시작도 분리."""
    result, bucket = [], []

    def flush():
        if bucket:
            for part in split_restarts(bucket):
                text = ''.join(w['text'] for w in part).strip()
                if norm(text):
                    conf = sum(float(w.get('confidence', 0)) for w in part) / len(part)
                    result.append({'start': float(part[0]['start']), 'end': min(float(duration), float(part[-1]['end'])),
                                   'text': text, 'confidence': round(conf, 3), **dict(zip(('quality', 'quality_notes'), take_quality(part))),
                                   **classify(text)})
            bucket.clear()
    for word in words:
        if bucket and (word['start'] - bucket[-1]['end'] > gap or word['end'] - bucket[0]['start'] > longest):
            flush()
        bucket.append(word)
        if re.search(r'[.?!。…]$', word['text'].strip()):
            flush()
    flush()
    return result


def mark_redundant(sentences):
    """말실수 뒤 재시도·반복 설명을 찾아 앞쪽(실패한) 문장에 `drop`을 표시한다.

    - 재시도: 뒤 문장과 유사(≥0.6)하고 앞 문장이 미완성이거나 더 짧음 → 앞 문장 삭제 후보
    - 반복: 거의 같은(≥0.85) 두 완성 문장 → 신뢰도×길이가 낮은 쪽 삭제 후보
    - 숫자·부정이 다르면 다른 주장이므로 둘 다 남기고 '확인 필요'
    """
    for i, a in enumerate(sentences):
        a.setdefault('drop', None)
        a.setdefault('review', [])
    parent = list(range(len(sentences)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    texts = [norm(x['text']) for x in sentences]
    for i, a in enumerate(sentences):
        na = texts[i]
        if a['mistake'] and i + 1 < len(sentences) and sentences[i + 1]['start'] - a['end'] < 10 and len(na) <= 25:
            a['drop'] = a['drop'] or ('retake', '말실수·촬영 지시 후 다시 말한 부분')
            continue
        for j in range(i + 1, min(len(sentences), i + 7)):
            b = sentences[j]
            if b['start'] - a['end'] > 20:
                break
            nb = texts[j]
            if len(na) < 4 or len(nb) < 4:
                continue
            sim = difflib.SequenceMatcher(None, na, nb, autojunk=False).ratio()
            if nb.startswith(na) or na.startswith(nb):
                sim = max(sim, .9)  # 한쪽이 다른 쪽의 시작 부분 = 같은 말을 이어서 다시 말함
            if sim < .6:
                continue
            if not critical_equal(na, nb):
                for x in (a, b):
                    x['review'].append('비슷한 두 문장의 숫자·부정 표현이 달라 반복으로 처리하지 않았어요')
                continue
            parent[find(j)] = find(i)
    groups = {}
    for i in range(len(sentences)):
        groups.setdefault(find(i), []).append(i)
    for members in groups.values():
        if len(members) < 2:
            continue
        longest = max(len(texts[i]) for i in members)
        # 후보: 완성된 문장이고 가장 긴 테이크의 75% 이상(중간에 끊긴 시도는 후보에서 제외)
        pool = [i for i in members if sentences[i]['complete'] and len(texts[i]) >= longest * .75 and not sentences[i]['drop']]
        pool = pool or [max(members, key=lambda i: len(texts[i]))]
        best = max(pool, key=lambda i: (sentences[i].get('quality', sentences[i]['confidence']), sentences[i]['confidence'], i))
        sentences[best]['takes'] = len(members)
        sentences[best]['review'] = [r for r in sentences[best]['review'] if '반복' not in r]
        for i in members:
            if i == best or sentences[i]['drop']:
                continue
            x = sentences[i]
            fragment = not x['complete'] or len(texts[i]) < longest * .75
            if fragment:
                x['drop'] = ('retake', '앞부분이 미완성이고 뒤에서 다시 말함(말실수 재시도)')
            else:
                notes = sentences[best].get('quality_notes') or []
                x['drop'] = ('repeat', f'같은 문장을 {len(members)}번 말함 · 가장 또렷한 테이크를 남김'
                                       + (f' (남긴 테이크: {", ".join(notes)})' if notes else ''))
    return sentences


# ----------------------------------------------------------- 장면(프레임) 분석
def frame_role(row):
    tags = row.get('tags') or {}
    for role in VISUAL_ROLES:
        if role in tags or (role == 'crosssection' and 'cream' in tags):
            return role
    return None


def build_shots(frames, merge_gap=2.5):
    """프레임 기록 → 같은 역할이 이어지는 장면(shot) 목록. 무음 구간도 포함."""
    shots = []
    for row in sorted(frames, key=lambda r: r['start']):
        role = frame_role(row)
        if not role:
            continue
        last = shots[-1] if shots else None
        if last and last['role'] == role and row['start'] - last['end'] <= merge_gap and row['shot'] - last['shot_last'] <= 1:
            last['end'] = max(last['end'], row['end'])
            last['shot_last'] = row['shot']
            last['frames'].append(row['id'])
        else:
            shots.append({'role': role, 'start': row['start'], 'end': row['end'], 'shot_first': row['shot'],
                          'shot_last': row['shot'], 'frames': [row['id']]})
    return shots


def product_for(frames_in_range, evidence, asset_id):
    """범위 안 제품 근거 → (이름, 근거 종류, 상태). 연속성만 있으면 '확인 필요'."""
    best = None
    for row in frames_in_range:
        for item in evidence.get((asset_id, row['id']), []):
            rank = {'confirmed': 3, 'candidate': 2, 'continuity_candidate': 1}.get(item['status'], 0)
            if not best or rank > best[0]:
                best = (rank, item)
    if not best:
        return None
    rank, item = best
    return {'name': item['name'], 'status': 'confirmed' if rank == 3 else '확인 필요',
            'basis': '; '.join(item.get('reasons', [])) or '근거 기록 없음',
            'uncertain': item.get('uncertainties', [])}


# ------------------------------------------------------------------ 점수·길이
SENTENCE_WEIGHT = [('score', 10), ('repurchase', 10), ('conclusion', 10), ('taste', 8), ('con', 7), ('price', 7), ('pro', 7),
                   ('question', 6), ('intro', 5), ('cooking', 4)]
VISUAL_WEIGHT = {'eating': 7, 'crosssection': 6, 'cutting': 5, 'opening': 5, 'packaging': 5, 'cooking': 3}
MUST_KEEP = {'repurchase', 'conclusion', 'score'}
LABEL_KO = {'score': '점수', 'repurchase': '재구매 의사', 'conclusion': '결론', 'taste': '맛·식감 평가', 'con': '아쉬운 점', 'price': '가격',
            'pro': '장점', 'question': '질문', 'intro': '제품 소개', 'cooking': '조리 설명', 'chat': '일반 발화'}


def sentence_score(unit):
    for label, weight in SENTENCE_WEIGHT:
        if label in unit['labels']:
            return weight
    return 2


def _subtract(interval, cuts):
    parts = [list(interval)]
    for c0, c1 in sorted(cuts):
        nxt = []
        for a, b in parts:
            if c1 <= a or c0 >= b:
                nxt.append([a, b])
            else:
                if a < c0:
                    nxt.append([a, c0])
                if c1 < b:
                    nxt.append([c1, b])
        parts = nxt
    return parts


def _overlap(a0, a1, b0, b1):
    return max(0., min(a1, b1) - max(a0, b0))


TAIL_MIN, TAIL_DEFAULT, TAIL_MAX = .2, .25, .35


def speech_tail(envelope, end):
    """문장 끝 뒤로 얼마나 더 둘지(초). 말끝이 흐려지며 잦아드는 소리까지 살린다.

    envelope: {'rate': 초당 값 수, 'db': 10ms 음량(dB) 목록, 'floor': 바닥 소음, 'voice': 말소리 기준}.
    음량이 말소리 기준 아래로 60ms 이상 내려간 지점 + 60ms. 범위 0.2~0.35초(사용자 요청: 0.2~0.3초 더). 정보가 없으면 0.25초
    (인식기의 단어 끝 시간이 실제 말끝보다 이른 경우가 많아서, 1116 재현에서 0.2~0.3초를 더 둬야 자연스러웠다).
    """
    if not envelope:
        return TAIL_DEFAULT
    rate, db = envelope['rate'], envelope['db']
    threshold = envelope['floor'] + .2 * (envelope['voice'] - envelope['floor'])   # 잦아드는 말끝(작은 소리)까지 말소리로 본다
    start = int(end * rate)
    quiet = 0
    for i in range(start, min(len(db), start + int(TAIL_MAX * rate) + 1)):
        quiet = quiet + 1 if db[i] < threshold else 0
        if quiet >= 6:
            return min(TAIL_MAX, max(TAIL_MIN, (i - 5) / rate - end + .06))
    return TAIL_MAX if start < len(db) else TAIL_DEFAULT


def _units_for_asset(asset, frames, evidence, rules, notes):
    """한 원본의 편집 단위(문장 단위 + 음성 없는 보존 장면 단위)."""
    duration = asset['metadata']['duration']
    words = [w for w in asset['analysis'].get('words', []) if 0 <= w['start'] < w['end'] <= duration + .001]
    sentences = mark_redundant(split_sentences(words, duration))
    shots = build_shots(frames)
    fast = rules['fast']
    pre = .08 if fast else .12
    envelope = asset.get('_envelope')
    units = []
    for s in sentences:
        roles = [(sh['role'], _overlap(s['start'], s['end'], sh['start'], sh['end'])) for sh in shots]
        roles = [r for r, o in sorted(roles, key=lambda x: -x[1]) if o > 0]
        rows = [r for r in frames if r['start'] < s['end'] and r['end'] > s['start']]
        labels = [l for l in s['labels'] if l in LABEL_KO] or ['chat']
        unit = {'kind': 'speech', 'asset_id': asset['id'], 'filename': asset['name'],
                'start': max(0., s['start'] - pre), 'end': min(duration, s['end'] + speech_tail(envelope, s['end'])), 'speech_start': s['start'],
                'speech_end': s['end'], 'text': s['text'], 'labels': labels, 'role': labels[0],
                'visual_roles': roles[:2], 'confidence': s['confidence'], 'drop': s['drop'],
                'review': list(s['review']), 'negated': s['negated'], 'numbers': s['numbers'],
                'texture': s['texture'], 'mistake': s['mistake'], 'complete': s['complete']}
        if s['confidence'] < .5:
            unit['review'].append('인식 신뢰도 낮음 · 원음 확인 필요')
        prod = product_for(rows, evidence, asset['id'])
        if prod:
            unit['product'] = prod
        units.append(unit)
    spans = [(u['speech_start'], u['speech_end']) for u in units]
    for sh in shots:
        if sh['role'] not in rules['keep']:
            continue
        # 음성과 겹치는 부분을 빼고 남는 '말 없는' 장면 조각만 별도 단위로
        pieces = [[sh['start'], min(sh['end'], duration)]]
        for a, b in spans:
            nxt = []
            for p0, p1 in pieces:
                if b <= p0 or a >= p1:
                    nxt.append([p0, p1])
                else:
                    if a - p0 >= .25:
                        nxt.append([p0, a])
                    if p1 - b >= .25:
                        nxt.append([b, p1])
            pieces = nxt
        rows = [r for r in frames if r['id'] in set(sh['frames'])]
        prod = product_for(rows, evidence, asset['id'])
        for p0, p1 in pieces:
            if p1 - p0 < .3:
                continue
            cap = rules.get('max_silent', STYLES[rules['style']]['max_silent_visual'])
            trimmed = p1 - p0 > cap
            unit = {'kind': 'visual', 'asset_id': asset['id'], 'filename': asset['name'], 'start': p0,
                    'end': p0 + cap if trimmed else p1, 'role': sh['role'], 'labels': [sh['role']], 'visual_roles': [sh['role']],
                    'text': '', 'review': [], 'drop': None,
                    'trimmed_tail': (p0 + cap, p1) if trimmed else None}
            if sh['role'] == 'eating':
                unit['review'].append('먹는 장면은 시각 모델 판단 · 원본 확인 권장')
            if prod:
                unit['product'] = prod
            units.append(unit)
    return sorted(units, key=lambda u: (u['start'], u['end']))


# ------------------------------------------------------------------- 메인 계획
def plan(assets, rules, frames_by_asset=None, evidence=None, fps=30, check=lambda: None):
    """assets: 영상 원본 리스트(분석 포함). 반환: clips, report."""
    frames_by_asset = frames_by_asset or {}
    evidence = evidence or {}
    style = STYLES[rules['style']]
    target_min, target_max = rules['target']
    units, removed, notes = [], [], []
    for asset in assets:
        check()
        if not asset['metadata'].get('has_video', True):
            continue
        if not asset['analysis'].get('words') and not frames_by_asset.get(asset['id']):
            notes.append(f'{asset["name"]}: 음성·장면 분석 결과가 없어 자동 선택하지 못했어요. 원본 전체를 유지합니다.')
            d = asset['metadata']['duration']
            units.append({'kind': 'whole', 'asset_id': asset['id'], 'filename': asset['name'], 'start': 0., 'end': d,
                          'role': 'unanalyzed', 'labels': [], 'visual_roles': [], 'text': '', 'drop': None,
                          'review': ['분석 없음 · 직접 확인']})
            continue
        units += _units_for_asset(asset, frames_by_asset.get(asset['id'], []), evidence, rules, notes)

    kept = []
    for u in units:
        if u['drop']:
            removed.append({'asset_id': u['asset_id'], 'filename': u['filename'], 'start': u['start'], 'end': u['end'],
                            'reason_code': u['drop'][0], 'reason': u['drop'][1], 'text': u['text']})
            continue
        if u['kind'] == 'speech' and u['mistake'] and 'retake' in rules['drop'] and not any(
                l in u['labels'] for l in ['taste', 'conclusion', 'repurchase', 'price']):
            removed.append({'asset_id': u['asset_id'], 'filename': u['filename'], 'start': u['start'], 'end': u['end'],
                            'reason_code': 'prep', 'reason': '촬영 지시·준비 발화', 'text': u['text']})
            continue
        if u['kind'] == 'speech' and u['labels'] == ['chat'] and 'taste' in rules['keep'] and rules['style'] != 'oneshot':
            # 후녹음 나레이션 유형은 촬영 중 잡담을 기본으로 쓰지 않음(원음은 앰비언트)
            pass
        if u.get('trimmed_tail'):
            a, b = u['trimmed_tail']
            removed.append({'asset_id': u['asset_id'], 'filename': u['filename'], 'start': a, 'end': b,
                            'reason_code': 'long_visual', 'reason': '말 없는 보존 장면이 길어 앞부분만 유지', 'text': ''})
        kept.append(u)

    # 첫 의미 있는 단위 이전의 준비 구간 삭제 사유 기록
    for asset in assets:
        mine = [u for u in kept if u['asset_id'] == asset['id'] and u['kind'] != 'whole']
        if mine and 'prep' in rules['drop']:
            first = min(u['start'] for u in mine)
            done = [(r['start'], r['end']) for r in removed if r['asset_id'] == asset['id'] and r['end'] <= first + .001]
            for a, b in _subtract([0., first], done):
                if b - a >= .3:
                    removed.append({'asset_id': asset['id'], 'filename': asset['name'], 'start': a, 'end': b,
                                    'reason_code': 'prep', 'reason': '첫 발화·보존 장면 이전(촬영 준비/대기)', 'text': ''})

    # 겹치는 단위 정리: 패딩끼리만 겹치므로 두 발화 사이의 중간점에서 나눈다(발화 자체는 보존).
    kept.sort(key=lambda u: (u['asset_id'], u['start']))
    for a, b in zip(kept, kept[1:]):
        if a['asset_id'] == b['asset_id'] and b['start'] < a['end']:
            floor = a.get('speech_end', a['start'])
            ceil = b.get('speech_start', b['end'])
            mid = min(max((a['end'] + b['start']) / 2, floor), ceil)
            a['end'], b['start'] = mid, mid
    kept = [u for u in kept if u['end'] - u['start'] >= 1 / fps]

    # 목표 길이: 낮은 우선순위부터 제외. 필수(결론)·문장 중간은 절대 자르지 않음.
    def total(items):
        return sum(u['end'] - u['start'] for u in items)

    def score(u):
        if u['kind'] == 'speech':
            s = sentence_score(u)
            if u['review']:
                s -= .5
            return s
        return VISUAL_WEIGHT.get(u['role'], 1) if u['role'] in rules['keep'] else 1

    warnings = []
    hook_unit = None
    laid_units = []
    if rules.get('overlay_eating', True):
        kept, overlaid, laid_units = overlay_eating(kept)
        if overlaid:
            notes.append(f'맛 평가 {overlaid}곳에 먹는·단면 화면을 얹었어요(소리는 평가 발화 그대로). 타임라인에서 확인하세요.')
    if total(kept) > target_max:
        order = sorted((u for u in kept if not (set(u['labels']) & MUST_KEEP)), key=lambda u: (score(u), -(u['end'] - u['start'])))
        for u in order:
            if total(kept) <= target_max:
                break
            kept.remove(u)
            removed.append({'asset_id': u['asset_id'], 'filename': u['filename'], 'start': u['start'], 'end': u['end'],
                            'reason_code': 'length', 'reason': f'목표 길이 {target_max}초 초과 · 우선순위 낮은 {LABEL_KO.get(u["role"], ROLE_LABEL.get(u["role"], u["role"]))}',
                            'text': u['text']})
        if total(kept) > target_max:
            warnings.append(f'보존해야 할 결론·문장을 자르지 않아 목표 {target_max}초를 {total(kept) - target_max:.1f}초 넘겼어요.')
    if total(kept) < target_min:
        warnings.append(f'편집본이 목표 최소 {target_min}초보다 {target_min - total(kept):.1f}초 짧아요. 원본에 쓸 만한 구간이 부족합니다(억지로 늘리지 않았어요).')

    # 순서: 기본은 촬영 순서(원본 업로드 순 → 시간 순). 필요한 경우에만 후킹·제품 묶기.
    asset_order = {a['id']: i for i, a in enumerate(assets)}
    kept.sort(key=lambda u: (asset_order.get(u['asset_id'], 0), u['start']))
    moved = []
    if rules['hook'] == 'speech' and len(kept) > 3:
        hook_unit = _pick_hook(kept)
        if hook_unit:
            idx = kept.index(hook_unit)
            if idx > 0:
                kept.insert(0, kept.pop(idx))
                moved.append({'text': hook_unit['text'], 'reason': '실제 발화의 핵심 질문·평가로 시작(문장 단독으로 의미 유지 확인)'})
    elif rules['hook'] == 'speech' or rules['hook'] == 'visual':
        pass
    if rules['group_products']:
        kept, group_notes = _group_by_product(kept)
        warnings += group_notes

    # 필수 요소 점검: 없으면 '없음'으로 보고(만들어 넣지 않음)
    missing = []
    have = {l for u in kept for l in u['labels']}
    if ({'conclusion', 'repurchase'} & rules['keep']) and not ({'conclusion', 'repurchase'} & have) and rules['style'] in ('oneshot', 'cook_mukbang', 'restaurant'):
        missing.append('실제로 말한 결론·재구매 의사를 찾지 못했어요. 추가하지 않았습니다.')
    if 'packaging' in rules['keep'] and 'packaging' not in have and not any('packaging' in u['visual_roles'] for u in kept) and rules['style'] != 'vlog':
        missing.append('제품·포장이 보이는 장면 후보를 찾지 못했어요.')
    if 'eating' in rules['keep'] and not any(('eating' in u['labels']) or ('eating' in u['visual_roles']) for u in kept) and rules['style'] in ('oneshot', 'cook_mukbang', 'restaurant'):
        missing.append('먹는 장면 후보를 찾지 못했어요.')

    if rules.get('hook_montage', True) and kept and kept[0]['kind'] == 'speech' and not kept[0].get('overlay'):
        shots = build_shots(frames_by_asset.get(kept[0]['asset_id'], []))
        pieces = hook_montage(kept[0], shots, fps)
        if pieces:
            kept[0]['montage'] = pieces
            notes.append(f'후킹 멘트 아래에 제품 장면 {len(pieces)}컷을 빠르게 얹었어요(완성본 1116 방식). 화면이 맞는지 확인하세요.')
    clips = _merge_clips(kept, assets, rules, fps)
    review_items = [{'filename': u['filename'], 'start': u['start'], 'end': u['end'], 'role': u['role'],
                     'review': u['review'] + (u.get('product', {}).get('uncertain', []) if u.get('product', {}).get('status') == '확인 필요' else [])}
                    for u in kept if u['review'] or u.get('product', {}).get('status') == '확인 필요']
    return {'clips': clips, 'units': [_public(u) for u in kept] + [_public(u) for u in laid_units], 'removed': sorted(removed, key=lambda r: (r['filename'], r['start'])),
            'moved': moved, 'warnings': warnings + notes, 'missing': missing, 'review': review_items,
            'seconds': round(total(kept), 3), 'target': list(rules['target']), 'style': rules['style'],
            'applied': rules['applied'], 'unapplied': rules['unapplied']}


def _public(u):
    out = {k: u.get(k) for k in ['kind', 'asset_id', 'filename', 'start', 'end', 'role', 'labels', 'text', 'review', 'visual_roles',
                                  'confidence', 'negated', 'numbers', 'product']}
    out['role_label'] = LABEL_KO.get(u['role']) or ROLE_LABEL.get(u['role'], u['role'])
    out['reason'] = _reason(u)
    out['status'] = '확인 필요' if u['review'] or u.get('product', {}).get('status') == '확인 필요' else '자동 선택'
    return out


def _reason(u):
    if u['kind'] == 'speech':
        text = ', '.join(LABEL_KO.get(l, l) for l in u['labels'])
        extra = f' · 화면: {", ".join(ROLE_LABEL.get(r, r) for r in u["visual_roles"])}' if u['visual_roles'] else ''
        return f'실제 발화({text}){extra}'
    if u['kind'] == 'visual' and u.get('overlaid'):
        return f'{ROLE_LABEL.get(u["role"], u["role"])} 장면 · 맛 평가 소리 위에 화면으로 사용'
    if u['kind'] == 'visual':
        return f'말 없는 {ROLE_LABEL.get(u["role"], u["role"])} 장면 · 음성이 없어도 보존'
    return '분석 결과가 없어 원본 유지'


def _pick_hook(units):
    """단독으로 의미가 유지되는 질문·평가 문장만 후킹으로 올린다(원래 맥락 보호)."""
    best = None
    for u in units[1:]:
        if u['kind'] != 'speech' or u['confidence'] < .7 or u['review'] or not u['complete']:
            continue
        if not ({'question', 'taste', 'con', 'pro'} & set(u['labels'])):
            continue
        if set(u['labels']) & {'repurchase'} or u['negated'] and 'taste' in u['labels']:
            continue  # 부정 평가는 앞뒤 맥락 없이 앞으로 옮기지 않음
        if re.match(r'^\s*(그래서|근데|그런데|그리고|그러니까|하지만|그래도|그리고)', u['text']) or re.search(r'(이거|그거|이건|그건|얘|걔|이게)\b', u['text']):
            continue  # 지시어·접속어: 순서를 바꾸면 의미가 달라질 수 있음
        length = u['speech_end'] - u['speech_start']
        if not 1.5 <= length <= 9:
            continue
        score = (2 if 'question' in u['labels'] else 1) + u['confidence']
        if not best or score > best[0]:
            best = (score, u)
    return best[1] if best else None


OVERLAY_ROLES = ('eating', 'crosssection', 'cutting', 'opening')


MONTAGE_FAST = ('packaging', 'opening')
MONTAGE_MAIN = ('eating', 'crosssection', 'cutting')


def hook_montage(hook, shots, fps=30, fast_piece=.28, max_fast=5):
    """후킹 발화 위에 제품 장면을 빠르게 얹는다(소리는 후킹 발화 그대로).

    완성본 1116 실측: 첫 3.5초 동안 제품을 하나씩 놓는 0.2초 컷 5개(1.4배속 기준, 원래 속도 약 0.28초)
    → 포장 클로즈업 → 한입 → 단면이 후킹 멘트 아래로 지나갔다. 같은 단면 컷은 본편에서 다시 쓰였다.
    반환: [(소리 기준 시작, 끝, 화면 시작, 역할)] — 후킹 발화 구간 안의 상대 시간이 아니라 원본 시간.
    """
    length = hook['end'] - hook['start']
    if length < 1.2:
        return []
    def spread(cands, n, gap):
        picked = []
        for sh in sorted(cands, key=lambda s: -(s['end'] - s['start'])):
            if all(abs(sh['start'] - p['start']) >= gap for p in picked):
                picked.append(sh)
            if len(picked) == n:
                break
        return sorted(picked, key=lambda s: s['start'])
    fast = spread([s for s in shots if s['role'] in MONTAGE_FAST and s['end'] - s['start'] >= fast_piece], max_fast, 5.)
    main = spread([s for s in shots if s['role'] in MONTAGE_MAIN and s['end'] - s['start'] >= .6], 2, 10.)
    step = 1 / fps
    snap = lambda x: round(x / step) * step
    pieces, t = [], snap(hook['start'])
    budget_fast = length - (.8 * len(main))
    for sh in fast:
        if t + fast_piece > hook['start'] + budget_fast:
            break
        mid = (sh['start'] + sh['end'] - fast_piece) / 2
        end = snap(t + fast_piece)
        pieces.append((t, end, mid, sh['role']))
        t = end
    if main:
        each = (hook['end'] - t) / len(main)
        if each >= .5:
            for k, sh in enumerate(main):
                end = snap(hook['end']) if k == len(main) - 1 else snap(t + each)
                take = min(end - t, sh['end'] - sh['start'])
                end = snap(t + take) if k < len(main) - 1 else end
                pieces.append((t, end, max(sh['start'], (sh['start'] + sh['end'] - (end - t)) / 2), sh['role']))
                t = end
    return pieces if len(pieces) >= 2 else []


def overlay_eating(kept, window=240.):
    """맛 평가 발화 위에 가까운 '말 없는 시식·단면 컷'을 화면으로 얹는다(소리는 발화 그대로).

    완성본 1116을 원본과 대조한 결과: 소리 컷 60개 중 28개가 이 방식(먹는 화면 + 나중에 말한 평가 소리)이었고,
    그중 22개는 화면이 소리보다 앞선 장면(중앙값 105초 전, 최대 147초 전)이며 화면도 촬영 순서대로 이어졌다.
    완성본 화면은 원본을 좌우반전한 상태였다(자동 적용하지 않음).
    제품을 들어 보이며 소개하는 말, 점수("N점 드릴게요"), 결론은 얼굴이 보이는 원래 화면을 그대로 쓴다.
    얹는 데 쓴 시식 컷은 단독 구간으로는 넣지 않는다(같은 장면이 두 번 나오지 않게).
    """
    pool = [{'unit': u, 'cursor': u['start']} for u in kept if u['kind'] == 'visual' and u['role'] in OVERLAY_ROLES]
    used, count = set(), 0
    for s in sorted((u for u in kept if u['kind'] == 'speech'), key=lambda u: (u['asset_id'], u['start'])):
        labels = set(s['labels'])
        if not labels & {'taste', 'pro', 'con'} or labels & {'score', 'conclusion', 'repurchase', 'intro'}:
            continue
        name = (s.get('product') or {}).get('name')
        best = None
        for p in pool:
            v = p['unit']
            if v['asset_id'] != s['asset_id'] or v['end'] - p['cursor'] < .6:
                continue
            other = (v.get('product') or {}).get('name')
            if name and other and name != other:
                continue
            gap = s['start'] - v['end'] if v['end'] <= s['start'] else (v['start'] - s['end']) * 4 + 1   # 먹고 나서 말한 경우를 우선
            if 0 <= gap <= window and (best is None or gap < best[0]):
                best = (gap, p)
        if not best:
            continue
        p = best[1]
        take = min(p['unit']['end'] - p['cursor'], s['end'] - s['start'])
        s['overlay'] = {'start': p['cursor'], 'end': p['cursor'] + take, 'role': p['unit']['role']}
        p['cursor'] += take
        used.add(id(p['unit']))
        count += 1
    laid = [u for u in kept if id(u) in used]
    for u in laid:
        u['overlaid'] = True
    return [u for u in kept if id(u) not in used], count, laid


def _group_by_product(units):
    """확실한 제품(confirmed)만 기준으로 묶는다. 근거 약한 단위는 앞 단위의 그룹에 붙인다."""
    notes, groups, order = [], {}, []
    current = None
    for u in units:
        p = u.get('product')
        name = p['name'] if p and p['status'] == 'confirmed' else None
        if name:
            current = name
        key = current or '_none'
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(u)
        if p and p['status'] != 'confirmed' and name is None:
            u['review'].append(f'제품 "{p["name"]}"은 연속성 근거만 있어 확정하지 않았어요')
    if len([k for k in order if k != '_none']) > 1:
        notes.append('여러 제품 감지: 제품별로 묶어 정렬했어요. 서로 다른 제품의 장면이 섞이지 않았는지 확인하세요.')
    return [u for k in order for u in groups[k]], notes


def _merge_clips(kept, assets, rules, fps):
    """연속·근접 단위를 한 클립으로 합침(0.5초 미만 공백은 자연스러운 호흡으로 유지)."""
    meta = {a['id']: a for a in assets}
    clips, cur = [], None
    for u in kept:
        a = meta[u['asset_id']]
        frame = _frame_for(a, rules)
        if u.get('montage'):
            if cur:
                clips.append(cur)
            for a0, a1, v0, role in u['montage']:
                clips.append({'asset_id': u['asset_id'], 'start': a0, 'end': a1, 'frame': frame,
                              'visual_asset_id': u['asset_id'], 'visual_start': v0, 'visual_end': v0 + (a1 - a0),
                              'guided': {'units': [{**_brief(u), 'reason': '후킹 몽타주 · 화면은 ' + ROLE_LABEL.get(role, role) + ' 컷'}]}})
            last = u['montage'][-1][1]
            cur = {'asset_id': u['asset_id'], 'start': last, 'end': u['end'], 'frame': frame,
                   'guided': {'units': [_brief(u)]}} if u['end'] - last >= 1 / fps else None
            continue
        over = u.get('overlay')
        if over:
            # 화면만 다른 장면(시식·단면)으로 바꾸는 구간은 따로 떼어 낸다. 시식 컷이 발화보다 짧으면 남는 뒷부분은 원래 화면.
            if cur:
                clips.append(cur)
            take = over['end'] - over['start']
            whole = (u['end'] - u['start']) - take < .4
            split = u['end'] if whole else u['start'] + take
            clips.append({'asset_id': u['asset_id'], 'start': u['start'], 'end': split, 'frame': frame,
                          'visual_asset_id': u['asset_id'], 'visual_start': over['start'], 'visual_end': over['end'],
                          'guided': {'units': [{**_brief(u), 'reason': _reason(u) + f' · 화면은 {ROLE_LABEL.get(over["role"], over["role"])} 컷'}]}})
            cur = None if whole else {'asset_id': u['asset_id'], 'start': split, 'end': u['end'], 'frame': frame,
                                      'guided': {'units': [_brief(u)]}}
            continue
        if cur and not cur.get('visual_asset_id') and cur['asset_id'] == u['asset_id'] and 0 <= u['start'] - cur['end'] < .5:
            cur['end'] = max(cur['end'], u['end'])
            cur['guided']['units'].append(_brief(u))
        else:
            if cur:
                clips.append(cur)
            cur = {'asset_id': u['asset_id'], 'start': u['start'], 'end': u['end'],
                   'frame': frame, 'guided': {'units': [_brief(u)]}}
    if cur:
        clips.append(cur)
    out = []
    for i, c in enumerate(clips, 1):
        first = c['guided']['units'][0]
        c['id'] = f'guided-{i:03}'
        c['label'] = f'{i}. {first["role_label"]}' + (f' · {first["text"][:30]}' if first['text'] else '')
        c['start'] = max(0., math.floor(c['start'] * fps + 1e-6) / fps)
        c['end'] = max(c['start'] + 1 / fps, math.ceil(c['end'] * fps - 1e-6) / fps)
        c['end'] = min(c['end'], math.floor(meta[c['asset_id']]['metadata']['duration'] * fps) / fps)
        if c.get('visual_asset_id'):
            limit = meta[c['visual_asset_id']]['metadata']['duration']
            c['visual_start'] = max(0., min(c['visual_start'], limit - 2 / fps))
            c['visual_end'] = min(limit, max(c['visual_start'] + 1 / fps, min(c['visual_end'], c['visual_start'] + c['end'] - c['start'])))
        if c['end'] > c['start']:
            out.append(c)
    return out


def _brief(u):
    return {'role': u['role'], 'role_label': LABEL_KO.get(u['role']) or ROLE_LABEL.get(u['role'], u['role']),
            'text': u['text'], 'start': u['start'], 'end': u['end'], 'reason': _reason(u),
            'product': (u.get('product') or {}).get('name'),
            'review': u['review']}


def _frame_for(asset, rules):
    mode = rules['frame']
    w, h = asset['metadata'].get('width') or 0, asset['metadata'].get('height') or 0
    rotation = asset['metadata'].get('rotation', 0)
    if rotation in (90, -90, 270, -270):
        w, h = h, w
    if mode == 'auto':
        # 세로 원본은 확대하지 않고 그대로, 가로 원본은 제품을 자르지 않도록 흐린 배경
        mode = 'fit' if h >= w else 'blur'
    return {'mode': mode, 'x': .5, 'y': .5, 'zoom': 1}


# ------------------------------------------------------- 영상 유형 추정/프로필
def detect_style(assets, frames_by_asset=None):
    """업로드 구성으로 5개 유형 중 추정. 사용자가 고른 값이 항상 우선."""
    frames_by_asset = frames_by_asset or {}
    videos = [a for a in assets if a['metadata'].get('has_video', True)]
    narration = [a for a in assets if not a['metadata'].get('has_video', True)]
    total = sum(a['metadata']['duration'] for a in videos) or 1
    spoken = sum(w['end'] - w['start'] for a in videos for w in a['analysis'].get('words', []))
    ratio = spoken / total
    rows = [r for a in videos for r in frames_by_asset.get(a['id'], [])]
    n = len(rows) or 1
    cooking = sum('cooking' in r.get('tags', {}) for r in rows) / n
    eating = sum('eating' in r.get('tags', {}) for r in rows) / n
    reasons = [f'영상 {len(videos)}개, 나레이션 파일 {len(narration)}개, 말하는 비율 {ratio:.0%}, 조리 장면 {cooking:.0%}, 먹는 장면 {eating:.0%}']
    if len(videos) <= 2 and not narration and ratio >= .3:
        return 'oneshot', .7, reasons
    if narration or ratio < .2 or len(videos) >= 4:
        if cooking >= .3:
            return ('recipe' if eating < .08 else 'cook_mukbang'), .5, reasons
        if eating >= .08:
            return 'restaurant', .4, reasons
        return 'vlog', .4, reasons
    return 'oneshot', .4, reasons


def learn_profile(state, assets):
    """사용자가 직접 다듬은 편집본에서 스타일 수치를 학습(프로젝트에 저장해 다음 편집에 사용)."""
    clips = state.get('clips', [])
    if len(clips) < 3:
        return None
    lengths = [c['end'] - c['start'] for c in clips]
    kept_pauses = []
    for a, b in zip(clips, clips[1:]):
        if a['asset_id'] == b['asset_id'] and b['start'] >= a['end']:
            kept_pauses.append(b['start'] - a['end'])
    lengths.sort()
    return {'clips': len(clips), 'avg_clip': round(sum(lengths) / len(lengths), 2), 'median_clip': round(lengths[len(lengths) // 2], 2),
            'total': round(sum(lengths), 2), 'avg_removed_gap': round(sum(kept_pauses) / len(kept_pauses), 2) if kept_pauses else None,
            'note': '직접 수정한 편집본 기준 통계입니다. 다음 자동 편집의 컷 길이 상한과 목표 길이에 참고합니다.'}


def apply_profile(rules, profile):
    """학습된 프로필로 목표 길이·컷 길이 상한을 조정(지침이 명시한 목표 길이는 유지)."""
    if not profile:
        return rules
    rules = dict(rules)
    if profile.get('median_clip') and rules['style'] != 'oneshot':
        rules['max_silent'] = max(2.0, min(8.0, profile['median_clip'] * 1.5))
        rules['applied'] = rules['applied'] + [f'내 편집 스타일 반영: 말 없는 컷 최대 {rules["max_silent"]:.1f}초']
    return rules


# ----------------------------------------------------------- 나레이션(후녹음) 연결
def narration_lines(asset, limit=60):
    """후녹음 나레이션 음성 → 문장 목록. 어떤 장면에 붙일지는 사용자가 확인한다."""
    duration = asset['metadata']['duration']
    sentences = [s for s in mark_redundant(split_sentences(asset['analysis'].get('words', []), duration, gap=.9)) if not s['drop']]
    return [{'index': i, 'asset_id': asset['id'], 'filename': asset['name'], 'start': round(max(0., s['start'] - .1), 3),
             'end': round(min(duration, s['end'] + .2), 3), 'text': s['text'], 'confidence': s['confidence'],
             'labels': [l for l in s['labels'] if l in LABEL_KO], 'status': 'pending', 'suggestions': [],
             'takes': s.get('takes', 1), 'quality_notes': s.get('quality_notes', [])}
            for i, s in enumerate(sentences[:limit])]


def link_narration(state, line, visual, assets, fps=30):
    """나레이션 한 문장을 사용자가 확인한 영상 구간에 연결한다.

    - 나레이션 음성이 원음을 대신하고, 영상은 선택 구간을 쓴다(visual_*).
    - 선택한 영상 구간과 겹치는 기존 촬영 원음 클립 부분은 대체한다.
    - 영상이 나레이션보다 짧으면 가능한 만큼 앞으로 연장하고, 그래도 짧으면 경고(마지막 프레임 유지).
    반환: (새 state, 경고 목록)
    """
    warnings = []
    narr_len = line['end'] - line['start']
    source = assets[visual['asset_id']]
    limit = source['metadata']['duration']
    v0 = max(0., min(float(visual['start']), limit - 1 / fps))
    v1 = min(limit, max(float(visual['end']), v0 + narr_len))
    if v1 - v0 < narr_len - 1 / fps:
        warnings.append('선택한 영상이 나레이션보다 짧아 마지막 프레임을 유지합니다. 다른 구간을 추가로 선택하는 것을 권장해요.')
    v1 = min(v1, v0 + narr_len)
    new = {'id': f'narr-{line["asset_id"][:6]}-{line["index"]}', 'asset_id': line['asset_id'], 'start': line['start'],
           'end': line['end'], 'visual_asset_id': visual['asset_id'], 'visual_start': v0, 'visual_end': max(v1, v0 + 1 / fps),
           'label': f'나레이션 {line["index"] + 1}. {line["text"][:30]}', 'frame': _frame_for(source, {'frame': 'auto'}),
           'guided': {'units': [{'role': 'narration', 'role_label': '나레이션', 'text': line['text'], 'start': line['start'],
                                  'end': line['end'], 'reason': '사용자가 확인한 장면에 나레이션 연결', 'product': None, 'review': []}]}}
    out, inserted = [], False
    clips = [c for c in state.get('clips', []) if c['id'] != new['id']]
    for clip in clips:
        if clip['asset_id'] == visual['asset_id'] and not clip.get('visual_asset_id') and clip['start'] < v1 and clip['end'] > v0:
            if not inserted:
                inserted = True
                out.append(('mark', None))
            for a, b in _subtract([clip['start'], clip['end']], [(v0, v1)]):
                if b - a >= 1 / fps:
                    out.append(('clip', {**clip, 'id': f'{clip["id"]}.{round(a * 1000)}', 'start': a, 'end': b}))
        else:
            out.append(('clip', clip))
    result = []
    for kind, value in out:
        result.append(new if kind == 'mark' else value)
    if not inserted:
        # 대체할 원음 클립이 없으면, 이미 연결된 나레이션 문장 순서에 맞춰 뒤에 붙임
        result.append(new)
    state = {**state, 'clips': result}
    return state, warnings
