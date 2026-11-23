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

from .guided_texts import TYPE_GUIDELINES

# 기본 편집 지침 = 원테이크 먹방 리뷰 지침. 유형별 지침은 guided_texts.TYPE_GUIDELINES.
DEFAULT_GUIDELINE = TYPE_GUIDELINES['oneshot']

# 이전 기본 지침(여러 종류 영상용). 이 지침이 저장된 프로젝트는 화면에서 새 기본 지침으로 바꿔 보여준다.
DEFAULT_GUIDELINE_GENERAL = """업로드한 영상에서 중요한 부분을 골라 세로 9:16 숏폼으로 편집해줘.

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

DEFAULT_GUIDELINE_COMMENTARY_OLD = """영화·TV·애니메이션 해석 영상을 심플하게 정리해줘.

- 말 사이의 무음은 모두 빼줘.
- 버벅이거나 말실수한 부분은 빼고, 같은 말을 여러 번 했으면 가장 잘 말한 한 번만 넣어줘.
- 말끝이 흐려지지 않게 문장 끝은 살려줘.
- 말한 순서는 그대로 두고, 길이를 맞추려고 내용을 빼지 마.

실제로 말하지 않은 내용은 만들지 마."""

DEFAULT_GUIDELINE_COMMENTARY = TYPE_GUIDELINES['commentary']
# 화면용: 유형 키 → 기본 지침. 'old'는 예전 기본 지침들(그대로 저장된 프로젝트는 새 지침으로 바꿔 보여준다).
GUIDELINES = {'default': DEFAULT_GUIDELINE, **TYPE_GUIDELINES}
OLD_GUIDELINES = [DEFAULT_GUIDELINE_GENERAL, DEFAULT_GUIDELINE_COMMENTARY_OLD]


def storyboard_guideline(guideline, storyboard):
    """영상 콘티에 '목표 N초'가 있으면 그 길이를 지침 맨 앞에 넣어 우선 적용한다(지침의 길이는 일반 템플릿이라서)."""
    m = re.search(r'목표\s*(?:길이\s*)?(?:는\s*)?(\d{1,3})\s*초', storyboard or '')
    if not m or not 5 <= int(m[1]) <= 600:
        return guideline
    seconds = int(m[1])
    return f'영상 콘티의 목표 길이는 {max(5, int(seconds * .85))}~{seconds}초.\n\n' + guideline


def default_for(style):
    return TYPE_GUIDELINES.get(style, DEFAULT_GUIDELINE)


def is_default_text(text):
    t = (text or '').strip()
    return not t or t in {g.strip() for g in list(TYPE_GUIDELINES.values()) + OLD_GUIDELINES}

# ---------------------------------------------------------------- 영상 유형(5종 + 해석 리뷰)
# 사용자가 설명한 5가지 제작 방식. 값은 시작점이며 지침·프로필이 덮어쓴다.
STYLES = {
    'oneshot': {
        'name': '원테이크 먹방 리뷰', 'target': (45, 60), 'hook': 'speech', 'narration': False,
        'max_silent_visual': 5.0, 'max_shot': None, 'frame': 'auto',
        'order': ['intro', 'opening', 'eating', 'taste', 'conclusion'],
        'note': '촬영 순서를 유지하고 준비·말실수·반복·긴 무음만 줄입니다.'},
    # 먹방 원본(말하면서 먹기) + 따로 찍은 무음 디테일 컷(패키지·단면·늘어남). 원본 발화가 중심.
    'product_mukbang': {
        'name': '제품컷 + 먹방 리뷰', 'target': (45, 60), 'hook': 'visual', 'narration': False,
        'max_silent_visual': 3.0, 'max_shot': 3.0, 'frame': 'auto',
        'order': ['intro', 'packaging', 'crosssection', 'eating', 'taste', 'conclusion'],
        'note': '먹방 원본의 실제 발화를 중심으로, 말하는 제품·특징에 맞는 디테일 컷(1~3초)을 덮습니다.'},
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
        # 지침서 '현장·체험형'(김장 완성본 67초): 60~70초 고정, 컷 1~2초, 현장 멘트는 가장 센 한두 마디만, 마지막은 단체 장면.
        'name': '브이로그·현장 체험 (짧은 컷 + 현장 멘트)', 'target': (60, 70), 'hook': 'visual', 'narration': True,
        'max_silent_visual': 2.0, 'max_shot': 2.0, 'frame': 'auto',
        'order': [], 'note': '60~70초 고정. 1~2초 컷을 이어 붙이고, 같은 동작은 한 컷만, 현장 멘트는 가장 센 한두 마디만 남깁니다.'},
    'restaurant': {
        'name': '맛집 리뷰 (짧은 컷 + 먹방 + 나레이션)', 'target': (22, 55), 'hook': 'visual', 'narration': True,
        'max_silent_visual': 3.0, 'max_shot': 4.0, 'frame': 'auto',
        'order': ['packaging', 'cooking', 'eating', 'taste', 'conclusion'],
        'note': '가게·메뉴·음식·먹방 컷 위주. 나레이션은 따로 연결합니다.'},
    # 채널 '이요저장소'(영화·TV·애니 해석) 쇼츠 1개(60초)에서 파악: 얼굴로 말하는 영상 + 작품 장면 겹침, 4구간(12/18/14/16초),
    # 질문형 제목, 마지막에 시청자 질문. 작품 장면 자동 인식은 아직 없어 장면 연결은 직접 합니다.
    'commentary': {
        'name': '영화·TV·애니 해석 리뷰 (말하는 영상 + 작품 장면)', 'target': (45, 65), 'hook': 'speech', 'narration': False,
        'max_silent_visual': 3.0, 'max_shot': None, 'frame': 'auto',
        'order': [], 'note': '심플 편집: 무음 제거 · 버벅인 부분 제거 · 가장 잘 말한 테이크만 · 말끝 보존 · 순서와 길이 그대로. 작품 장면은 직접 연결합니다.'},
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
POST_NARRATION = re.compile(r'후\s*나레이션|나레이션\s*후\s*(작업|녹음)|후\s*녹음|나레이션\s*(포함|따로)')
UNSUPPORTED = ['음악', '효과음', '전환 효과', '얼굴 추적', '줌인', '자막 스타일']


SCENE_STOP = {'장면', '화면', '구간', '우선으로', '골라줘', '그대로', '살리고', '자르지', '끝날', '때까지', '현장음', '바로',
              '다음', '넘어가', '각각', '짧게', '없으니', '찾지', '말고', '있는', '보여주는', '나오는', '하는', '이어', '첫', '마지막',
              '있으면', '넣고', '없으면', '건너뛰어', '한마디', '한마디가', '끝나면', '이어서', '전부', '각', '모습', '써'}
PARTICLE = re.compile(r'(으로|에게|에서|까지|부터|이랑|하고|이나|을|를|이|가|은|는|에|의|와|과|로|도|만)$')


def _scene_terms(text):
    terms = []
    for tok in re.findall(r'[가-힣A-Za-z0-9]{2,}', text):
        stem = PARTICLE.sub('', tok)
        if len(stem) >= 2 and stem not in SCENE_STOP and tok not in SCENE_STOP:
            terms.append(stem)
    return list(dict.fromkeys(terms))


def _parse_scene_line(line):
    """'3. 진행자가 … 장면. 현장음을 그대로 살리고 …' 같은 번호 장면 한 줄 → 찾을 장면 요청."""
    m = re.match(r'^(?:(\d+)\s*[.)]|(마지막)\s*[:：])\s*(.+)$', line)
    if not m:
        return None
    body = m[3].strip()
    first = bool(re.match(r'첫\s*장면\s*[:：]', body))
    body = re.sub(r'^첫\s*장면\s*[:：]\s*', '', body)
    absent_part = ' '.join(re.findall(r'([^.,]*?)없으니\s*찾지', body))
    main = re.sub(r'[^.]*?없으니\s*찾지\s*(말고|마\.?)', '', body)
    main = re.sub(r'(자르|삭제하)지\s*마', '', main)
    absent = [k for k, p in KEEP_WORDS if re.search(p, absent_part)]
    roles = [k for k, p in KEEP_WORDS if re.search(p, main) and k not in absent]
    names = [n.strip() for n in re.split(r'[,，]', re.split(r'무대|공연', body)[0]) if n.strip()] if '각각' in body else []
    return {'n': int(m[1]) if m[1] else 999, 'text': body, 'first': first, 'last': bool(m[2]),
            'live': bool(re.search(r'현장음.*(살리|그대로)|끝날\s*때까지\s*자르지', body)),
            'optional': bool(re.search(r'있으면.*(건너뛰|빼)', body)),
            'short': bool(re.search(r'짧게|1\s*~\s*2\s*초', body)),
            'count': max(1, min(6, len(names))) if names else 1,
            'absent': absent, 'roles': roles, 'terms': _scene_terms(main)}


def _parse_caption_line(line, rules):
    """자막·표기 항목 → 별도 표기(고정 문구·강조 자막·이름 표시). 실제 자막은 말한 그대로라 여기서 만들지 않는다."""
    ov = rules.setdefault('overlays', [])
    if m := re.search(r'(상단|하단|가운데|위|아래)[^\']*[\'‘"“]([^\'’"”]{1,30})[\'’"”][^\n]*처음부터\s*끝까지', line):
        ov.append({'kind': 'fixed', 'text': m[2], 'position': m[1]})
    elif m := re.search(r'강조\s*자막\s*[:：]\s*(.+)$', line):
        text = m[1].strip().strip('\'"‘’“”')
        ov.append({'kind': 'emphasis', 'text': text[:14], 'position': '가운데'})
    else:
        for subject, label in re.findall(r'([^,]+?)(?:이|가)?\s*처음\s*나올\s*때\s*[\'‘"“]([^\'’"”]{1,30})[\'’"”]', line):
            ov.append({'kind': 'name', 'text': label, 'subject': _scene_terms(subject), 'position': '상단'})


def assign_scenes(units, rules, hits=None):
    """지시문의 '남길 장면' 순서대로 각 장면에 맞는 구간을 고른다.

    점수: 장면 설명의 단어가 실제 발화에 나오는 정도 + 장면 역할(포장·개봉·시식 등) + 화면 검색(CLIP·OCR) 후보와 겹침.
    '현장음 살리기'는 이어지는 발화까지 끝까지, '짧게'는 말 없는 컷을 2초 이내로, '없으니 찾지 마'는 그 역할을 제외한다.
    반환: (배치된 단위 목록, 경고 목록, 찾은 장면 수)
    """
    hits = hits or {}
    scenes = sorted(rules['scenes'], key=lambda s: (0 if s['first'] else 2 if s['last'] else 1, s['n']))
    used, out, warn, found = set(), [], [], 0
    for k, sc in enumerate(scenes):
        idx = rules['scenes'].index(sc)
        scored = []
        for u in units:
            if id(u) in used or u['kind'] == 'whole':
                continue
            roles = set(u['visual_roles'] if u['kind'] == 'speech' else [u['role']]) | set(u['labels'])
            if roles & set(sc['absent']):
                continue
            text = canonical_ko(u.get('text', '') + ' ' + ((u.get('product') or {}).get('name') or ''))
            hit_terms = sum(t in text or (len(t) >= 3 and t[:-1] in text) for t in sc['terms'])
            s = min(1., hit_terms / min(4, len(sc['terms']))) if sc['terms'] else 0
            s += .8 if roles & set(sc['roles']) else 0
            for h in hits.get(idx, []):
                if h['asset_id'] == u['asset_id'] and h['start'] < u['end'] and h['end'] > u['start']:
                    s = max(s, s + (1.2 if h.get('exact') else .5))
            if sc['live'] and u['kind'] != 'speech':
                s -= .5
            if s >= .5:
                scored.append((s, u))
        scored.sort(key=lambda x: -x[0])
        picked = []
        for s, u in scored:
            if all(abs(u['start'] - p['start']) >= 10 or u['asset_id'] != p['asset_id'] for p in picked):
                picked.append(u)
            if len(picked) == sc['count']:
                break
        if not picked:
            if not sc['optional']:
                warn.append(f'남길 장면 {sc["n"] if sc["n"] < 999 else "마지막"}: "{sc["text"][:40]}" 에 맞는 구간을 찾지 못했어요. 비슷한 장면으로 대신하지 않았어요.')
            continue
        found += 1
        if sc['live']:
            # 현장 멘트는 끝날 때까지: 바로 이어지는 발화를 함께 넣는다.
            u = picked[0]
            for v in sorted((x for x in units if x['asset_id'] == u['asset_id'] and x['kind'] == 'speech' and x['start'] >= u['end'] - .01), key=lambda x: x['start'])[:3]:
                if v['start'] - max(p['end'] for p in picked) < .8 and id(v) not in used and v not in picked:
                    picked.append(v)
                else:
                    break
        for u in sorted(picked, key=lambda x: (x['asset_id'], x['start'])):
            used.add(id(u))
            if (sc['short'] or sc['count'] > 1) and u['kind'] != 'speech' and u['end'] - u['start'] > (2. if sc['short'] else 3.):
                u = {**u, 'end': u['start'] + (2. if sc['short'] else 3.)}
            out.append({**u, 'scene': sc['n']})
    return out, warn, found


def canonical_ko(text):
    return re.sub(r'[^가-힣A-Za-z0-9]', '', text or '')


def overlay_items(overlays, clips):
    """표기(고정 문구·강조 자막·이름 표시)를 현재 타임라인 시간으로 바꾼다. 편집을 고쳐도 원본 위치 기준으로 다시 계산된다."""
    pos, starts = 0., []
    for c in clips:
        starts.append(pos)
        pos += c['end'] - c['start']
    items = []
    for o in overlays or []:
        if o['kind'] == 'fixed':
            items.append({'text': o['text'], 'start': 0., 'end': pos})
            continue
        for c, t0 in zip(clips, starts):
            a = o.get('anchor')
            if a and c['asset_id'] == a['asset_id'] and c['start'] - .01 <= a['src'] < c['end']:
                t = t0 + max(0., a['src'] - c['start'])
                items.append({'text': o['text'], 'start': t, 'end': min(pos, t + (2.5 if o['kind'] == 'emphasis' else 2.))})
                break
    return sorted(items, key=lambda i: i['start'])


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
        head = re.match(r'^(남길 장면|줄일 부분|구성|자막\s*·?\s*표기)\s*(\([^)]*\))?\s*:', line)
        if head:
            section = {'남길 장면': 'keep', '줄일 부분': 'drop', '구성': 'order'}.get(head[1], 'caption')
            continue
        if section == 'caption':
            _parse_caption_line(line, rules)
            continue
        if section == 'keep' and (scene := _parse_scene_line(line)):
            rules.setdefault('scenes', []).append(scene)
            rules['keep'] |= set(scene['roles'])
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
    if rules.get('scenes'):
        rules['applied'].append(f'남길 장면 {len(rules["scenes"])}개를 지시문 순서대로 배치')
        rules['hook'] = 'none'   # 첫 장면은 지시문이 정한다
    if rules.get('overlays'):
        rules['applied'].append('자막·표기 ' + ' · '.join(o['text'] for o in rules['overlays']) + ' (별도 표기 SRT)')
    rules['applied'] += ['준비·재촬영·반복·긴 무음 줄이기', '문장 끝 보존(말끝 여유 0.2~0.35초)']
    # 먹방·시식형에서만 쓰는 연출(완성본 1116에서 배운 것). 해석·브이로그 영상에는 적용하지 않는다.
    if style == 'commentary':
        # 해석 영상은 단순하게: 무음 제거 · 버벅인 부분 빼고 가장 잘 말한 테이크만 · 말끝 보존 · 순서와 길이는 그대로.
        rules.update(tight=True, no_trim=True, hook='none', protect_silent=False)
        rules['applied'] = [a for a in rules['applied'] if not a.startswith('목표 길이')]
        rules['applied'] += ['문장 사이·문장 안의 무음 제거', '여러 번 말한 문장은 가장 잘 말한 한 번만', '말한 순서 그대로 · 길이 맞추려고 빼지 않음']
    food = style in ('oneshot', 'product_mukbang', 'cook_mukbang', 'restaurant')
    rules['bites'] = food   # 먹방: 먹는 화면 위에 바로 뒤 소감 목소리를 깐다(시식 나레이션)
    # 목표 길이는 '완성본(배속 후)' 길이다. 사용자는 캡컷에서 배속을 건다(완성본 1123: 1.3배속, 1116: 1.4배속).
    # 그래서 원본에서 남길 분량 = 목표 × 배속. 이전엔 배속 전 길이로 맞춰 맛 평가 문장이 너무 많이 빠졌다(1123 대비 6문장).
    m = re.search(r'(\d(?:\.\d+)?)\s*배(?:속)?', text)
    rules['playback'] = float(m[1]) if m and 1 <= float(m[1]) <= 2 else (1.0 if re.search(r'배속\s*(없|안|하지)', text) or not food else 1.3)
    if rules['playback'] != 1:
        rules['applied'].append(f'목표 길이는 {rules["playback"]:g}배속 후 기준 · 원본 분량 {rules["target"][0] * rules["playback"]:.0f}~{rules["target"][1] * rules["playback"]:.0f}초 남김(배속은 캡컷에서)')
    rules['overlay_eating'] = food and not re.search(r'평가\s*소리.*얹지\s*마|화면\s*바꾸지\s*마', text)
    rules['hook_montage'] = (food or style == 'recipe') and not re.search(r'몽타주\s*(빼|없이|쓰지)', text)
    # 첫 후킹 나레이션을 캡컷에서 따로 녹음하는 영상(사용자 편집본 1123: 첫 10초 = 후녹음 나레이션 + 제품 모아 보여 주기 컷).
    # 영상마다 다르므로 프로젝트 이름이나 지침에 '후 나레이션'이 적혀 있을 때만 그 자리를 비워 둔다.
    rules['post_narration'] = bool(POST_NARRATION.search(text)) and not re.search(r'후\s*나레이션\s*(없|안|빼|제외)', text)
    if rules['post_narration']:
        rules['applied'].append('첫 부분에 후 나레이션(캡컷 녹음) 자리: 제품 모아 보여 주기·상자·단면 컷 약 10초')
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
    ('conclusion', r'여러분은?.*(보셨|생각|어떠|어땠|궁금)|(어떻게|어떤)\s*(보|느끼|생각)'),   # 시청자에게 묻는 마무리 질문
    ('conclusion', r'제일\s*맛있었|가장\s*맛있었|(제일|가장)\s*(좋았|맛있는)|1\s*위|원\s*픽|최애'),          # 여러 제품 중 고른 결론   # 시청자에게 묻는 마무리 질문
    ('question', r'\?|까요|나요|할까|일까|인가요|궁금|왜\s'),
    ('cooking', r'넣[고어은]|붓|돌려|돌리|섞|끓|굽|볶|올려|올리|자르|뿌리|익히|부수|전자레인지|\d+\s*분'),
    ('intro', r'오늘은|이번에|소개|신상|편의점|출시|나왔|새로\s*나|이\s*제품|제품은'),
    # 제품을 들고 설명하는 말(순서·구성·재료)과 다른 제품과의 비교. 1122 원본에서 이 말이 전부 빠져 먹방만 남았다.
    ('describe', r'^\s*(먼저|첫\s*번째|두\s*번째|세\s*번째|다음(은|으로)|마지막(은|으로))|부터는|들어[가갔있간]|코팅|필링|토핑|시럽|크림이|칩이|인데\s*$|인데요?\s*$'),
    ('compare', r'비하면|비해서?|보다(는|도)?\s|비교|차이|똑같|다르|달라'),
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
        if len(head) >= 4 and len(tail) >= len(head) and tail.startswith(head):   # 같은 말을 통째로 두 번 한 경우도
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
                    pauses = [(float(a['end']), float(b['start'])) for a, b in zip(part, part[1:]) if b['start'] - a['end'] > .3]
                    result.append({'start': float(part[0]['start']), 'end': min(float(duration), float(part[-1]['end'])),
                                   'text': text, 'confidence': round(conf, 3), 'pauses': pauses,
                                   'word_times': [(float(w['start']), float(w['end'])) for w in part], **dict(zip(('quality', 'quality_notes'), take_quality(part))),
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
            if min(len(na), len(nb)) < 6 and not (nb.startswith(na) or na.startswith(nb)):
                continue   # "소금우유" 같은 짧은 조각은 앞부분이 같을 때만 재시도로 본다(이어서 한 설명이 빠지지 않게)
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
SENTENCE_WEIGHT = [('score', 10), ('repurchase', 10), ('conclusion', 10), ('wrapup', 9.5), ('compare', 9), ('intro', 9), ('describe', 9), ('taste', 8), ('con', 7), ('price', 7), ('pro', 7),
                   ('question', 6), ('cooking', 4)]
VISUAL_WEIGHT = {'eating': 7, 'crosssection': 6, 'cutting': 5, 'opening': 5, 'packaging': 5, 'cooking': 3}
MUST_KEEP = {'repurchase', 'conclusion', 'score'}
LABEL_KO = {'score': '점수', 'wrapup': '전체 총평', 'repurchase': '재구매 의사', 'conclusion': '결론', 'taste': '맛·식감 평가', 'con': '아쉬운 점', 'price': '가격',
            'pro': '장점', 'question': '질문', 'intro': '제품 소개', 'describe': '제품 설명', 'compare': '비교', 'cooking': '조리 설명', 'chat': '일반 발화'}


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


VOICE_LEAD = .15        # 실제 목소리(VAD) 시작 앞 여유: 첫 자음이 잘리지 않게
VOICE_REACH = 1.2       # 인식기 단어 시간이 실제 목소리보다 늦을 때 앞으로 당겨 올 수 있는 최대 거리
PAUSE_KEEP = (.18, .12)  # 문장 안 긴 쉼을 줄일 때 남기는 앞·뒤 여유(합 0.3초 = 자연스러운 숨)
PAUSE_LONG = .5          # 이보다 긴 문장 안 쉼만 줄인다


def snap_to_voice(start, end, voice, lo=0., hi=float('inf')):
    """인식기(Whisper) 문장 시간 → 실제 목소리(VAD) 기준 시간.

    실제 원테이크 먹방 원본(1122 가나 프리미엄)에서 Whisper 단어 시간이 실제 목소리보다 0.4~1초 늦거나
    말끝이 0.4초 이상 무음 쪽으로 늘어나 있었다. 그대로 자르면 문장 첫 단어가 잘리고 끝에 무음이 남는다.
    voice: [[시작, 끝], ...] 원본 전체 VAD 말소리 구간. lo/hi: 앞 문장 끝·뒤 문장 시작(넘지 않음).
    반환: (목소리 시작, 목소리 끝, 문장 안 무음 [(a, b), ...]).
    """
    if not voice:
        return start, end, []
    inside = [(a, b) for a, b in voice if b > start and a < end]
    if not inside:
        return start, end, []
    before = [(a, b) for a, b in voice if b <= inside[0][0]]
    if before and before[-1][1] > start - .35 and before[-1][0] >= lo and before[-1][0] >= start - VOICE_REACH:
        inside.insert(0, before[-1])   # 인식기가 첫 단어를 늦게 찍었다: 바로 앞 목소리가 이 문장의 시작
    s = max(inside[0][0], start - VOICE_REACH, lo)
    e = min(inside[-1][1], hi, end + .6)
    covered = sum(max(0., min(b, end) - max(a, start)) for a, b in inside)
    if covered < .4 * (end - start):
        # 배경 소음이 커서 VAD가 목소리를 일부만 잡은 경우: 인식기 시간에서 0.25초까지만 줄인다(말 잘림 방지).
        s, e = min(s, start + .25), max(e, min(end - .25, hi))
    if e - s < .15:
        return start, end, []
    gaps = [(b, a) for (_, b), (a, _) in zip(inside, inside[1:]) if s < b < a < e]
    return s, e, gaps


SWALLOW = 1.5   # 단어 하나가 이보다 길면 인식기가 그 사이 말(같은 말 반복·재시작)을 받아 적지 않고 삼킨 것


def skip_swallowed(s0, s1, gaps, word_times, tol=.3):
    """인식기가 받아 적지 않은 '같은 말 반복'을 뺀다 → (새 시작, 새 쉼 목록).

    실제 원본(1122 가나 프리미엄 134~144초): '필링까지'가 133.2~141.6초 한 단어로 찍혔고, 그 사이 목소리 구간 3개는
    같은 말을 다시 시작한 부분이었다(사용자: '두 번씩 말하는 버그'). 완성본 1123은 마지막 시도(138초~)만 썼다.
    그래서 긴 단어가 덮는 목소리 구간 중 다른 단어가 시작하지 않는 구간은 마지막 하나만 남긴다.
    """
    pieces, t = [], s0
    for a, b in sorted(gaps):
        pieces.append((t, a))
        t = b
    pieces.append((t, s1))
    starts = [w0 for w0, _ in word_times]
    def spoken(p):
        return any(p[0] - tol <= x <= p[1] + tol for x in starts)
    drop = set()
    for w0, w1 in word_times:
        if w1 - w0 <= SWALLOW:
            continue
        silent = [i for i, p in enumerate(pieces) if p[1] > w0 - tol and p[0] < w1 and not spoken(p)]
        drop |= set(silent[:-1])
    if not drop or len(drop) >= len(pieces):
        return s0, gaps
    kept = [p for i, p in enumerate(pieces) if i not in drop]
    return kept[0][0], [(a[1], b[0]) for a, b in zip(kept, kept[1:])]


def _units_for_asset(asset, frames, evidence, rules, notes):
    """한 원본의 편집 단위(문장 단위 + 음성 없는 보존 장면 단위)."""
    duration = asset['metadata']['duration']
    words = [w for w in asset['analysis'].get('words', []) if 0 <= w['start'] < w['end'] <= duration + .001]
    sentences = mark_redundant(split_sentences(words, duration))
    shots = build_shots(frames)
    fast = rules['fast']
    pre = .08 if fast else .12
    envelope = asset.get('_envelope')
    voice = [(float(a), float(b)) for a, b in (asset['analysis'].get('speech') or []) if b > a]
    prev_end = 0.
    for i, s in enumerate(sentences):
        nxt = sentences[i + 1]['start'] if i + 1 < len(sentences) else duration
        s0, s1, gaps = snap_to_voice(s['start'], s['end'], voice, prev_end, nxt)
        if gaps:
            s0, gaps = skip_swallowed(s0, s1, gaps, s.get('word_times', []))
        s['voice'] = (s0, s1, gaps) if (s0, s1) != (s['start'], s['end']) or gaps else None
        prev_end = s1 if s['voice'] else s['end']
    units = []
    for s in sentences:
        if s.get('voice'):
            # 실제 목소리 시간으로 교체. 문장 안 긴 쉼(무음)도 목소리 기준으로 다시 잡는다.
            s0, s1, gaps = s['voice']
            s = {**s, 'start': s0, 'end': s1, 'pauses': gaps, 'voice_pre': VOICE_LEAD}
        roles = [(sh['role'], _overlap(s['start'], s['end'], sh['start'], sh['end'])) for sh in shots]
        roles = [r for r, o in sorted(roles, key=lambda x: -x[1]) if o > 0]
        rows = [r for r in frames if r['start'] < s['end'] and r['end'] > s['start']]
        labels = [l for l in s['labels'] if l in LABEL_KO] or ['chat']
        lead = s.get('voice_pre', pre)
        unit = {'kind': 'speech', 'asset_id': asset['id'], 'filename': asset['name'],
                'start': max(0., s['start'] - lead), 'end': min(duration, s['end'] + speech_tail(envelope, s['end'])), 'speech_start': s['start'],
                'speech_end': s['end'], 'text': s['text'], 'labels': labels, 'role': labels[0],
                'visual_roles': roles[:2], 'confidence': s['confidence'], 'drop': s['drop'],
                'review': list(s['review']), 'negated': s['negated'], 'numbers': s['numbers'],
                'texture': s['texture'], 'mistake': s['mistake'], 'complete': s['complete']}
        if rules.get('tight'):
            # 문장 안의 쉼도 뺀다. 쉼 앞 단어의 말끝은 살린다(말끝 흐림 방지).
            cuts = []
            for a, b in s.get('pauses', []):
                c0, c1 = a + speech_tail(envelope, a), b - pre
                if c1 - c0 >= .12:
                    cuts.append((c0, c1))
            unit['pauses'] = cuts
        elif s.get('voice'):
            # 먹방 등: 문장 안에서 0.5초 넘게 멈춘 곳(씹는 중·생각 중)은 0.3초 숨만 남기고 줄인다.
            unit['pauses'] = [(a + PAUSE_KEEP[0], b - PAUSE_KEEP[1]) for a, b in s['pauses']
                              if b - a > PAUSE_LONG and b - PAUSE_KEEP[1] - (a + PAUSE_KEEP[0]) >= .15]
        if s['confidence'] < .5:
            unit['review'].append('인식 신뢰도 낮음 · 원음 확인 필요')
        prod = product_for(rows, evidence, asset['id'])
        if prod:
            unit['product'] = prod
        units.append(unit)
    # 인식기가 쉼 때문에 한 설명을 여러 조각으로 나눈 경우("먼저 CU 소금우유는" / "밀크초콜릿에" / "필링까지 캐러멜칩이 들어갔다는데"):
    # 제품 설명·비교 문장과 4초 안으로 붙은 이름 없는 조각도 같은 설명으로 본다(말이 중간에 끊기지 않게).
    for _ in range(3):
        for a, b in zip(units, units[1:]):
            if b['speech_start'] - a['speech_end'] > 4:
                continue
            for x, y in ((a, b), (b, a)):
                if x['labels'] == ['chat'] and set(y['labels']) & {'describe', 'compare', 'intro'}:
                    x['labels'], x['role'] = ['describe'], 'describe'
    spans = [(u['speech_start'], u['speech_end']) for u in units]
    for sh in ([] if rules.get('tight') else shots):   # 말 위주 편집(해석 영상)은 말 없는 장면을 따로 넣지 않는다
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
    if rules.get('bites'):
        units = _add_bites(units, sentences, frames, voice, asset, duration)
    return sorted(units, key=lambda u: (u['start'], u['end']))


BITE_GAP = 12.     # 맛 평가 앞에서 이만큼 말이 없고 그 사이 '먹기' 장면이 보이면 시식으로 본다
BITE_GAP_BLIND = 20.   # '먹기' 장면을 못 찾았을 때는 더 오래 말이 없어야 시식으로 본다
BITE_SHOW = (.4, 2.)   # 먹는 장면(시각 모델 '먹기' 프레임) 앞·뒤로 보여 줄 길이(이 화면 위에 소감 목소리가 나온다)
BITE_BLIND = 1.8   # '먹기' 장면을 못 찾았을 때 말하기 직전 씹는 화면 길이


def _add_bites(units, sentences, frames, voice, asset, duration):
    """시식 나레이션: 한동안 말없이 먹은 뒤 맛을 말하는 곳마다, 먹는 화면 위에 그 소감 목소리를 깐다.

    1122 원본에서 실제로 본 문제: 먹는 장면이 전부 빠져서 먹방 장면이 통으로 사라졌다. 그렇다고 말없이 먹는 장면을
    따로 넣으면 지루하다(사용자 피드백 2026-11-22: '먹방 장면은 지루하니까 먹방 중이거나 먹방 후에 소감 ... 나레이션을 넣음').
    그래서 먹는 순간(첫 한입)의 화면을 소감 발화 앞부분에 얹고(소리는 소감 그대로), 남은 말은 얼굴 화면으로 돌아온다.
    제품을 들고 설명하거나 화면을 보며 설명하는 말은 원래 화면 그대로 둔다(여기서 다루지 않음).
    """
    eats = sorted(r['start'] for r in frames if 'eating' in (r.get('tags') or {}))
    spoken = sorted((s['voice'][0] if s.get('voice') else s['start'], s['voice'][1] if s.get('voice') else s['end']) for s in sentences)
    speech_units = [u for u in units if u['kind'] == 'speech']
    shown = []
    for u in speech_units:
        if u['drop'] or not set(u['labels']) & {'taste', 'pro', 'con'} or set(u['labels']) & INTRO_LABELS:
            continue
        s0 = u['speech_start']
        quiet_from = max([b for a, b in spoken if b <= s0 - .05] + [b for a, b in voice if b <= s0 - .05] + [0.])
        eat = [t for t in eats if quiet_from + .5 <= t <= s0 - .5]
        if not eat:   # '먹기' 태그가 없어도 그 쉬는 동안 가장 먹는 장면 같은 순간(시각 모델 점수 최대)을 쓴다
            best = _best_moment(frames, quiet_from + .5, s0 - .5, ('eating',))
            eat = [best] if best is not None else []
        if s0 - quiet_from < (BITE_GAP if eat else BITE_GAP_BLIND):
            continue
        if eat:
            t = eat[-1]   # 말하기 전 마지막으로 먹은 순간
            a, b = max(quiet_from + .3, t - BITE_SHOW[0]), min(t + BITE_SHOW[1], u['start'])
        else:
            a, b = max(quiet_from + .3, u['start'] - .3 - BITE_BLIND), u['start'] - .3
        talk = u['end'] - u['start']
        if b - a < .6 or talk < .6:
            continue
        take = min(b - a, talk)
        u['overlay'] = {'start': a, 'end': a + take, 'role': 'eating', 'narration': True}
        u['after_bite'] = True   # 다른 시식 컷을 또 얹지 않고, 후킹 몽타주로도 쓰지 않는다
        shown.append((a, a + take))
    # 나레이션 화면으로 쓴 먹는 장면은 따로 넣지 않는다(같은 장면이 두 번 나오지 않게)
    return [u for u in units if u['kind'] != 'visual' or not any(u['start'] < y and u['end'] > x for x, y in shown)]


def _best_moment(frames, a, b, keys, avoid=(), near=3.):
    """a~b초 사이 장면 중 시각 모델 점수(keys 합)가 가장 높은 순간. 점수 기록이 없으면 None.

    말하는 원본의 '먹기' 태그는 드물다(1123 원본 20분 중 17장면). 그래도 말없이 먹는 구간 안에서 점수가 가장 높은 장면은
    사용자가 직접 고른 먹방 컷과 맞았다(먹기 최대 250·496·1192초 ↔ 직접 편집 246·487·1188초,
    들고 보여 주기+속 최대 253·491·771초 ↔ 254·493·771초).
    """
    rows = [r for r in frames if a <= r['start'] <= b and r.get('similarities')
            and all(abs(r['start'] - t) > near for t in avoid)]
    if not rows:
        return None
    return max(rows, key=lambda r: sum(r['similarities'].get(k, 0) for k in keys))['start']


EAT_SESSION = 8.   # 말없이 이만큼 이어지면 먹는 구간으로 본다


def _eating_moments(asset, frames):
    """말하는 원본의 말없는 먹는 구간마다 '한입 먹는 순간'과 '먹은 단면을 카메라에 보여 주는 순간'을 하나씩 고른다.

    사용자 직접 편집본 1123: 맛 평가와 총평 말 위에 이런 먹방 컷(0.5~1.5초)을 자주 얹었다(62초 중 약 14번).
    이전 자동 편집은 '먹기' 태그가 붙은 장면만 써서 먹방 모습이 거의 안 나왔다(사용자: '먹방 모습이 사라짐').
    """
    spoken = sorted((float(w['start']), float(w['end'])) for w in asset['analysis'].get('words', []))
    if not spoken or not frames:
        return []
    moments = []
    edges = [(0., spoken[0][0])] + [(spoken[i][1], spoken[i + 1][0]) for i in range(len(spoken) - 1)]
    for a, b in edges:
        if b - a < EAT_SESSION:
            continue
        show = _best_moment(frames, a + .5, b - .5, ('holding', 'cream', 'crosssection'))
        bite = _best_moment(frames, a + .5, b - .5, ('eating',), [show] if show is not None else [])
        for t, role in ((bite, 'eating'), (show, 'crosssection')):
            if t is not None:
                moments.append({'kind': 'visual', 'asset_id': asset['id'], 'filename': asset.get('name', ''), 'start': max(a, t - .6),
                                'end': min(b, t + .8), 'role': role, 'labels': [role], 'visual_roles': [role], 'text': '',
                                'review': [], 'drop': None, 'eating_moment': True})
    return sorted(moments, key=lambda m: m['start'])


def _mark_wrapup(units):
    """여러 제품 리뷰에서 마지막 점수 뒤 말 = 전체 총평(먹어 본 소감·아쉬운 점·제일 맛있던 것·질문).

    사용자 직접 편집본 1123(원본과 소리 대조): 마지막 점수 뒤 '네 가지 다 먹어봤는데 맛은 있거든요? … 편의점 네 군데를
    돌아서 사야 된다는 게 별로 … 묶어서 판매해 주세요 … 제일 맛있었던 건 소금우유 … 여러분은?'을 거의 다 썼다(약 25초).
    이전 자동 편집은 이 말들을 '일반 발화'로 보고 길이 때문에 전부 뺐다.
    """
    by_asset = {}
    for u in units:
        if u['kind'] == 'speech':
            by_asset.setdefault(u['asset_id'], []).append(u)
    for items in by_asset.values():
        scores = [u for u in items if 'score' in u['labels']]
        if len(scores) < 2:
            continue
        last = max(u['speech_end'] for u in scores)
        for u in items:
            if u['speech_start'] > last and not u['drop'] and not set(u['labels']) & MUST_KEEP:
                u['labels'] = ['wrapup'] + [l for l in u['labels'] if l != 'chat']
                u['role'] = 'wrapup'


# ------------------------------------------------------------------- 메인 계획
def plan(assets, rules, frames_by_asset=None, evidence=None, fps=30, check=lambda: None):
    """assets: 영상 원본 리스트(분석 포함). 반환: clips, report."""
    frames_by_asset = frames_by_asset or {}
    evidence = evidence or {}
    style = STYLES[rules['style']]
    target_min, target_max = (round(t * rules.get('playback', 1), 1) for t in rules['target'])   # 원본 기준 분량
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
    _mark_wrapup(units)

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
    # 말 없는 장면이 문장 앞뒤 여유(말끝)와 겹치면 장면 쪽을 줄인다(말끝 보존, 같은 소리 두 번 재생 방지).
    kept.sort(key=lambda u: (u['asset_id'], u['start']))
    for a, b in zip(kept, kept[1:]):
        if a['asset_id'] == b['asset_id'] and b['start'] < a['end']:
            if a['kind'] == 'speech' and b['kind'] == 'visual':
                b['start'] = min(a['end'], b['end'])
            elif a['kind'] == 'visual' and b['kind'] == 'speech':
                a['end'] = max(b['start'], a['start'])
            else:
                floor = a.get('speech_end', a['start'])
                ceil = b.get('speech_start', b['end'])
                mid = min(max((a['end'] + b['start']) / 2, floor), ceil)
                a['end'], b['start'] = mid, mid
    kept = [u for u in kept if u['end'] - u['start'] >= (.3 if u['kind'] == 'visual' else 1 / fps)]
    # 한 단위가 다른 단위 안에 통째로 들어간 경우(인식 시간이 겹친 문장 등)도 정리: 앞 단위가 끝난 뒤부터만 쓴다.
    tidy, last = [], {}
    for u in kept:
        end = last.get(u['asset_id'], -1.)
        if u['start'] < end:
            if u['end'] <= end + 1 / fps:
                continue
            u['start'] = end
        last[u['asset_id']] = max(end, u['end'])
        tidy.append(u)
    kept = tidy

    # 목표 길이: 낮은 우선순위부터 제외. 필수(결론)·문장 중간은 절대 자르지 않음.
    def length(u):
        cut = sum(c1 - c0 for c0, c1 in u.get('pauses', []) if u['start'] < c0 < c1 < u['end'])
        return u['end'] - u['start'] - cut

    def total(items):
        return sum(length(u) for u in items)

    def score(u):
        if u['kind'] == 'speech':
            s = sentence_score(u)
            if u['review']:
                s -= .5
            # 완성본 1123에서 사용자가 남긴 평가 = 자기 취향·이유가 담긴 문장("저는 크런키한 식감이 좋더라고요",
            # "진짜 꿀이랑 배맛이 너무 잘 나는데요?", "묶어서 판매해주세요"). 뺀 문장 = "맛있다." 같은 두세 단어 감탄.
            # 영상 콘티 [실제 반응] 단서(커스터드·짠맛·호지차 향·꿀맛 …)가 든 평가는 남긴다.
            if set(u['labels']) & {'taste', 'pro', 'con'} and any(w in u['text'] for ws in (rules.get('conti_hints') or {}).values() for w in ws):
                s += 1.5
            if set(u['labels']) & {'taste', 'pro', 'con'}:
                if OPINION.search(u['text']):
                    s += 1.5
                elif len(u['text'].split()) <= 2:
                    s -= 1.5
            return s
        return VISUAL_WEIGHT.get(u['role'], 1) if u['role'] in rules['keep'] else 1

    warnings = []
    hook_unit = None
    laid_units = []
    scene_mode = False
    if rules.get('scenes'):
        placed, scene_warn, found = assign_scenes(kept, rules, rules.get('scene_hits'))
        if found and found >= max(1, len(rules['scenes']) // 2):
            kept, scene_mode = placed, True
            warnings += scene_warn
            notes.append(f'지시문의 남길 장면 {len(rules["scenes"])}개 중 {found}개를 찾아 그 순서대로 배치했어요.')
        else:
            warnings.append('지시문의 남길 장면을 절반 이상 찾지 못해 일반 자동 편집으로 만들었어요. 장면 묘사를 더 구체적으로 써 주세요.')
            warnings += scene_warn
    if rules.get('overlay_eating', True) and not scene_mode:
        moments = [m for a in assets if a['analysis'].get('words') for m in _eating_moments(a, frames_by_asset.get(a['id'], []))]
        kept, overlaid, laid_units = overlay_eating(kept, extra=moments)
        if overlaid:
            notes.append(f'맛 평가 {overlaid}곳에 먹는·단면 화면을 얹었어요(소리는 평가 발화 그대로). 타임라인에서 확인하세요.')
    if total(kept) > target_max and not rules.get('no_trim') and not scene_mode:
        # 시식 장면(먹는 순간·표정 반응)은 음성이 없어도 길이 때문에 빼지 않는다(지침: 음성이 없다는 이유만으로 삭제하지 마).
        # 제품마다 처음 들고 설명한 말도 남긴다(소개 → 시식 → 평가 → 점수 구성. '먹방만 넣으면 안 된다').
        _anchor_product_intros(kept)
        order = sorted((u for u in kept if not (set(u['labels']) & MUST_KEEP) and not u.get('bite') and not u.get('after_bite')
                        and not u.get('intro_anchor')), key=lambda u: (score(u), -length(u)))
        for u in order:
            if total(kept) <= target_max:
                break
            kept.remove(u)
            removed.append({'asset_id': u['asset_id'], 'filename': u['filename'], 'start': u['start'], 'end': u['end'],
                            'reason_code': 'length', 'reason': f'목표 길이 {target_max}초 초과 · 우선순위 낮은 {LABEL_KO.get(u["role"], ROLE_LABEL.get(u["role"], u["role"]))}',
                            'text': u['text']})
        if total(kept) > target_max:
            warnings.append(f'보존해야 할 결론·문장을 자르지 않아 목표 {target_max}초를 {total(kept) - target_max:.1f}초 넘겼어요.')
    if scene_mode and total(kept) > target_max:
        warnings.append(f'지시문 장면을 모두 넣어 목표 {target_max}초를 {total(kept) - target_max:.1f}초 넘겼어요. 먼저 줄일 장면을 확인하세요.')
    if total(kept) < target_min and not rules.get('no_trim'):
        warnings.append(f'편집본이 목표 최소 {target_min}초보다 {target_min - total(kept):.1f}초 짧아요. 원본에 쓸 만한 구간이 부족합니다(억지로 늘리지 않았어요).')

    # 순서: 기본은 촬영 순서(원본 업로드 순 → 시간 순). 필요한 경우에만 후킹·제품 묶기.
    asset_order = {a['id']: i for i, a in enumerate(assets)}
    if not scene_mode:
        kept.sort(key=lambda u: (asset_order.get(u['asset_id'], 0), u['start']))
    moved = []
    if rules['hook'] == 'speech' and len(kept) > 3 and not scene_mode:
        hook_unit = _pick_hook(kept)
        if hook_unit:
            idx = kept.index(hook_unit)
            if idx > 0:
                kept.insert(0, kept.pop(idx))
                moved.append({'text': hook_unit['text'], 'reason': '실제 발화의 핵심 질문·평가로 시작(문장 단독으로 의미 유지 확인)'})
    elif rules['hook'] == 'speech' or rules['hook'] == 'visual':
        pass
    if rules['group_products'] and not scene_mode:
        kept, group_notes = _group_by_product(kept)
        warnings += group_notes

    # 필수 요소 점검: 없으면 '없음'으로 보고(만들어 넣지 않음)
    missing = []
    have = {l for u in kept for l in u['labels']}
    if ({'conclusion', 'repurchase'} & rules['keep']) and not ({'conclusion', 'repurchase'} & have) and rules['style'] in ('oneshot', 'product_mukbang', 'cook_mukbang', 'restaurant'):
        missing.append('실제로 말한 결론·재구매 의사를 찾지 못했어요. 추가하지 않았습니다.')
    if 'packaging' in rules['keep'] and 'packaging' not in have and not any('packaging' in u['visual_roles'] for u in kept) and rules['style'] != 'vlog':
        missing.append('제품·포장이 보이는 장면 후보를 찾지 못했어요.')
    if 'eating' in rules['keep'] and not any(('eating' in u['labels']) or ('eating' in u['visual_roles']) for u in kept) and rules['style'] in ('oneshot', 'product_mukbang', 'cook_mukbang', 'restaurant'):
        missing.append('먹는 장면 후보를 찾지 못했어요.')

    names = auto_products(kept) if rules.get('bites') and not scene_mode else {}
    if names:
        for u, k in _product_blocks(kept):
            if k in names and not u.get('product'):
                u['auto_product'] = names[k][0]
    broll = _detail_shots(assets, frames_by_asset, evidence, names) if rules.get('bites') and not scene_mode else []
    order = [names[k][0] for k in sorted(names)]
    # 후 나레이션 자리가 있으면 제품별 첫 컷(상자)을 그 자리에 쓰고, 나머지를 설명 발화에 쓴다(한 컷은 한 번만).
    story = _storyboard(broll, order, _detail_wants(kept), 1) if broll and rules.get('post_narration') else None
    # 첫 장면을 먼저 정한다(사용자 편집본 1123: 첫 장면은 제품 여러 개를 함께 들어 보이는 컷). 그다음 제품별 디테일 컷.
    # 영상 콘티 첫 줄들이 원본에 없는 나레이션이면 그 읽는 길이(배속 전 원본 기준)만큼 채운다.
    slot_len = min(20., max(6., rules['narration_seconds'] * rules.get('playback', 1))) if rules.get('narration_seconds') else 11.
    slot = _opening_slot(broll, order, fps, length=slot_len, story=story) if rules.get('post_narration') and broll and not scene_mode else []
    if slot:
        notes.append(f'첫 {sum(u["end"] - u["start"] for u in slot):.0f}초(원본 기준)는 후 나레이션 자리예요: 제품 모아 보여 주기·상자·단면 컷 {len(slot)}개(원본 소리). 캡컷에서 나레이션을 녹음해 얹으세요.')
    if not slot and rules.get('hook_montage', True) and not scene_mode and kept and kept[0]['kind'] == 'speech' and not kept[0].get('overlay'):
        pieces = _opening_lineup(kept[0], broll, fps) if broll else []
        if pieces:
            kept[0]['montage'] = pieces
            notes.append(f'첫 멘트 아래에 제품 여러 개를 들어 보이는 컷 {len(pieces)}개를 이어 붙였어요(직접 편집본 1123 방식).')
    if broll:
        laid = _overlay_details([u for u in kept if not u.get('montage')], broll, story)
        if laid:
            notes.append(f'제품 설명 발화 위에 따로 찍은 같은 제품 디테일 컷 {laid}개를 얹었어요(소리는 발화 그대로). 제품마다 촬영 구간 처음·가운데·끝에서 서로 다른 장면으로 골랐어요.')
    kept = slot + kept
    again = _drop_repeats(kept)
    if again:
        notes.append(f'같은 장면이 두 번 나오지 않게 겹치는 얹은 화면 {again}개를 뺐어요(그 자리는 원래 화면).')
    kept = _cut_pauses(kept)   # 문장 안 긴 쉼 줄이기(해석 영상은 모든 쉼, 그 외는 0.5초 넘는 쉼)
    clips = _merge_clips(kept, assets, rules, fps)
    overlays = []
    for o in rules.get('overlays', []):
        o = dict(o)
        if o['kind'] == 'emphasis' and clips:
            o['anchor'] = {'asset_id': clips[0]['asset_id'], 'src': clips[0]['start']}
        elif o['kind'] == 'name':
            want = o.get('subject', [])[:1]   # '부스'·'현장' 같은 일반 단어 말고 이름 자체로 찾는다
            hit = next((u for u in kept if want and any(t in canonical_ko(u.get('text', '')) for t in want)), None)
            if not hit and scene_mode:
                sc = next((s for s in rules['scenes'] if any(t in s['text'] for t in want)), None)
                hit = next((u for u in kept if sc and u.get('scene') == sc['n']), None)
            if hit:
                o['anchor'] = {'asset_id': hit['asset_id'], 'src': hit['start']}
            else:
                warnings.append(f'표기 "{o["text"]}"를 넣을 위치를 찾지 못했어요. 캡컷에서 직접 넣어 주세요.')
        overlays.append(o)
    review_items = [{'filename': u['filename'], 'start': u['start'], 'end': u['end'], 'role': u['role'],
                     'review': u['review'] + (u.get('product', {}).get('uncertain', []) if u.get('product', {}).get('status') == '확인 필요' else [])}
                    for u in kept if u['review'] or u.get('product', {}).get('status') == '확인 필요']
    return {'clips': clips, 'units': [_public(u) for u in kept] + [_public(u) for u in laid_units], 'removed': sorted(removed, key=lambda r: (r['filename'], r['start'])),
            'moved': moved, 'warnings': warnings + notes, 'missing': missing, 'review': review_items,
            'seconds': round(total(kept), 3), 'target': list(rules['target']), 'style': rules['style'],
            'applied': rules['applied'], 'unapplied': rules['unapplied'], 'overlays': overlays}


INTRO_LABELS = {'describe', 'intro', 'compare'}
OPINION = re.compile(r'저는|제가|진짜|너무|제일|좋더라|좋아하|괜찮겠|해\s*주세요|했으면|아쉬|궁금')
CONTENT = re.compile(r'들어[가갔있간]|코팅|필링|토핑|크림|칩|시럽|함량|겉은|안에는|속에는')


def _anchor_product_intros(kept):
    """제품 구간(점수 발화로 끝남)마다 제품을 소개한 말과 구성을 설명한 말 하나를 표시한다. 길이 맞추기에서 빼지 않는다.

    1122 원본: "먼저 CU 소금우유는 … 필링까지 캐러멜칩이 들어갔다는데", "마지막은 세븐일레븐의 크림브륄레인데 … 카라멜칩이 들어있고"
    같은 제품 소개가 전부 빠지고 먹방만 남았다(사용자: '먹방만 넣으면 안 된다').
    - 소개: 구간의 첫 소개·설명 문장 + 4초 안에 이어 말한 조각(합 5초까지, 제품 이름이 잘리지 않게)
    - 구성 설명: 구간 안에서 재료·구성 단어가 가장 많은 문장 하나(같으면 짧은 것)
    마지막 점수 뒤(마무리 잡담)에는 표시하지 않는다.
    """
    def spoken(u):   # 문장 안 긴 쉼은 잘리므로 뺀 길이
        return u['end'] - u['start'] - sum(b - a for a, b in u.get('pauses', []) if u['start'] < a < b < u['end'])
    speech = sorted((u for u in kept if u['kind'] == 'speech'), key=lambda u: (u['asset_id'], u['start']))
    segments, cur = [], []
    for u in speech:
        if cur and cur[-1]['asset_id'] != u['asset_id']:
            segments.append((cur, False))
            cur = []
        cur.append(u)
        if 'score' in u['labels']:
            segments.append((cur, True))
            cur = []
    for seg, scored in segments:
        if not scored:
            continue
        intro = [u for u in seg if set(u['labels']) & INTRO_LABELS]
        if not intro:
            continue
        chain = [intro[0]]
        for u in intro[1:]:
            if u['speech_start'] - chain[-1]['speech_end'] > 4 or sum(map(spoken, chain)) + spoken(u) > 5:
                break
            chain.append(u)
        rest = [u for u in intro if u not in chain and CONTENT.search(u['text'])]
        if rest:
            chain.append(max(rest, key=lambda u: (len(CONTENT.findall(u['text'])), -spoken(u))))
        for u in chain:
            u['intro_anchor'] = True


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
    if u.get('opening_slot'):
        return f'후 나레이션 자리 · {ROLE_LABEL.get(u["role"], u["role"])} 컷(캡컷에서 나레이션 녹음)'
    if u.get('bite'):
        return '시식 장면 · 먹는 순간과 표정 반응(얼굴 화면 그대로)'
    if u['kind'] == 'visual' and u.get('overlaid'):
        return f'{ROLE_LABEL.get(u["role"], u["role"])} 장면 · 맛 평가 소리 위에 화면으로 사용'
    if u['kind'] == 'visual':
        return f'말 없는 {ROLE_LABEL.get(u["role"], u["role"])} 장면 · 음성이 없어도 보존'
    return '분석 결과가 없어 원본 유지'


def _pick_hook(units):
    """단독으로 의미가 유지되는 질문·평가 문장만 후킹으로 올린다(원래 맥락 보호)."""
    best = None
    for u in units[1:]:
        if u['kind'] != 'speech' or u.get('after_bite') or u['confidence'] < .7 or u['review'] or not u['complete']:
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


DETAIL_TAKE = (8, .03)   # 단어 8개 미만·말소리 3% 미만인 영상 = 따로 찍은 디테일 컷(제품·포장·단면)
DETAIL_SHOW = (.8, 1.4)  # 디테일 컷 하나를 보여 주는 길이(완성본 1123 실측 0.75~1.5초)
DETAIL_LABELS = {'describe', 'intro', 'compare', 'taste', 'pro', 'con', 'price'}
FACE_LABELS = {'score', 'conclusion', 'repurchase', 'question', 'wrapup'}


def _product_blocks(kept):
    """발화 순서대로 제품 구간을 나눈다: 'N점 드릴게요'(점수)가 나오면 다음 제품."""
    blocks, k = [], 0
    for u in sorted((u for u in kept if u['kind'] == 'speech'), key=lambda u: (u['asset_id'], u['start'])):
        blocks.append((u, k))
        if 'score' in u['labels']:
            k += 1
    return blocks


NAME_STOP = {'먼저', '마지막', '마지막은', '다음', '다음은', '이건', '이거', '오늘', '오늘은', '편의점', '초콜릿', '다크', '밀크', '가나', '프리미엄',
             '제품', '그리고', '이렇게', '진짜', '완전', '이마트', '세븐일레븐', '씨유', '지에스', '모양', '똑같아요', '겉은', '안에는', '속에는', '들어갔습니다', '들어갔다는데', '들어있고', '들어가서'}
JOSA = ('부터는', '부터', '인데', '에는', '이라', '이에요', '예요', '은', '는', '이', '가', '도', '의', '에', '를', '을')


def _name_tokens(text):
    out = []
    for raw in re.findall(r'[가-힣A-Za-z0-9]+', text):
        word = re.sub(r'[^가-힣]', '', raw)
        for j in JOSA:
            if word.endswith(j) and len(word) - len(j) >= 2:
                word = word[:-len(j)]
                break
        if len(word) >= 2 and word not in NAME_STOP:
            out.append(word)
    return out


def _bigrams(text):
    t = re.sub(r'[^가-힣]', '', text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def auto_products(kept):
    """등록한 제품이 없을 때: 제품마다(점수로 나눈 구간) 소개·설명 말에서 이름 후보를 뽑는다 → {구간: (이름, 그 구간만의 글자쌍)}.

    1122 가나 프리미엄 프로젝트는 제품 등록이 없어 디테일 컷 제품 근거가 하나도 없었다. 사용자 편집본 1123을 원본과 맞춰 보니
    디테일 컷은 정확히 말하는 제품 것만 썼다(소금우유 설명 위 = 소금우유 상자). 포장 글자 인식(OCR)은 저화질에서도
    '호지지'(호지차), '허니어'(허니페어)처럼 일부를 읽으므로, 말한 이름과 겹치는 글자쌍으로 제품을 붙인다.
    """
    tokens, firsts, scored = {}, {}, set()
    for u, k in _product_blocks(kept):
        if 'score' in u['labels']:
            scored.add(k)
        if set(u['labels']) & INTRO_LABELS:
            words = _name_tokens(u['text'])
            tokens.setdefault(k, []).extend(words)
            if len(firsts.setdefault(k, [])) < 4:
                firsts[k].extend(words)
    tokens = {k: v for k, v in tokens.items() if k in scored}   # 마지막 점수 뒤 총평은 제품 구간이 아님
    grams = {k: set().union(*(_bigrams(t) for t in v)) for k, v in tokens.items() if v}
    result = {}
    for k in grams:
        others = set().union(*(g for j, g in grams.items() if j != k)) if len(grams) > 1 else set()
        unique = grams[k] - others
        pool = firsts.get(k) or tokens[k]
        name = next((t for t in pool if len(_bigrams(t) & unique) >= 2), None) or max(pool, key=lambda t: (len(_bigrams(t) & unique), len(t)))
        mark = _bigrams(name) & unique
        if mark:
            result[k] = (name, mark)
    return result


MULTI = '__여러 제품__'


def _frame_product(row, evidence, asset_id, names):
    found = product_for([row], evidence or {}, asset_id)
    if found:
        return found['name']
    if not names:
        return None
    text = ''.join(o.get('text', '') for o in row.get('ocr') or [])
    got = _bigrams(text)
    hits = sorted(((len(got & g), name) for name, g in names.values()), reverse=True)
    if len(hits) > 1 and hits[1][0] >= 1:
        return MULTI   # 상자 여러 개가 함께 보임(제품 모아 보여 주기) → 한 제품 설명에는 쓰지 않고 첫 장면 후보
    if hits and hits[0][0] >= 1:
        return hits[0][1]
    return None


def _detail_shots(assets, frames_by_asset, evidence, names=None):
    """말소리가 거의 없는 '디테일 컷' 영상을 0.8~1.2초 장면으로 나누고, 제품 근거(등록 제품 또는 말한 이름과 포장 글자)를 붙인다.

    완성본 1123(가나 프리미엄 4종) 역추출: 화면 시간의 약 35%가 따로 찍은 디테일 컷(포장·개봉·단면, 0.75~1.5초)이었고
    첫 10초는 제품 4종을 들어 보이는 컷, 그 뒤로는 제품 소개·설명 발화 위에 같은 제품 컷이 얹혀 있었다.
    디테일 영상은 한 번에 이어 찍어 장면 전환이 없으므로(원본 260초 = 장면 1개) 장면 단위가 아니라 시간 단위로 나눈다.
    제품을 한 상자씩 이어서 찍으므로, 같은 제품 근거 사이(25초 이내) 구간도 그 제품으로 본다.
    """
    speaking = [a for a in assets if a['metadata'].get('has_video', True) and len(a['analysis'].get('words', [])) >= DETAIL_TAKE[0]]
    details = [a for a in assets if a['metadata'].get('has_video', True) and a not in speaking
               and sum(b - a0 for a0, b in a['analysis'].get('speech') or []) < DETAIL_TAKE[1] * a['metadata'].get('duration', 1)]
    if not details or not speaking:
        return []
    shots = []
    for a in details:
        rows = sorted(frames_by_asset.get(a['id'], []), key=lambda r: r['start'])
        labels = [_frame_product(r, evidence, a['id'], names) for r in rows]
        multi = [r['start'] for r, p in zip(rows, labels) if p == MULTI]
        labels = [MULTI if p and p != MULTI and any(abs(r['start'] - t) <= 1.5 for t in multi) else p for r, p in zip(rows, labels)]
        for i, p in enumerate(list(labels)):
            if p and p != MULTI:   # 근거 한 장면 앞뒤 3초(같은 장면)는 같은 상자
                for m in range(len(rows)):
                    if not labels[m] and rows[m]['shot'] == rows[i]['shot'] and abs(rows[m]['start'] - rows[i]['start']) <= 3:
                        labels[m] = p
        known = [(i, p) for i, p in enumerate(labels) if p and p != MULTI]
        for (i, p), (j, q) in zip(known, known[1:]):
            if p == q and rows[j]['start'] - rows[i]['start'] <= 25:
                for m in range(i + 1, j):
                    labels[m] = labels[m] or p
        # 상자를 연 뒤 낱개를 펼친 장면엔 글자가 거의 없다(1123: 크림브륄레 160초 앞면 → 166초 연 상자 → 188초 낱개).
        # 그래서 한 제품의 마지막 근거 뒤, 다음 제품 근거 3초 전까지(최대 40초) 글자가 거의 없는 장면은 같은 제품으로 본다.
        known = [(i, p) for i, p in enumerate(labels) if p]
        for n, (i, p) in enumerate(known):
            if p == MULTI:
                continue
            stop = rows[known[n + 1][0]]['start'] - 3 if n + 1 < len(known) else float('inf')
            for m in range(i + 1, len(rows)):
                if labels[m] or rows[m]['start'] > min(stop, rows[i]['start'] + 40) or rows[m]['shot'] != rows[i]['shot']:
                    break
                if len(rows[m].get('ocr') or []) <= 2:   # 글자가 여럿 보이면 상자 여러 개일 수 있어 비워 둔다
                    labels[m] = p
        i = 0
        while i < len(rows):
            j = i
            while j + 1 < len(rows) and labels[j + 1] == labels[i] and rows[j + 1]['shot'] == rows[i]['shot'] \
                    and rows[j + 1]['start'] - rows[i]['start'] < DETAIL_SHOW[1]:
                j += 1
            start, end = rows[i]['start'], rows[j]['end']
            if end - start >= DETAIL_SHOW[0] and labels[i] != MULTI:
                tags = {}
                for r in rows[i:j + 1]:
                    for tag, v in (r.get('tags') or {}).items():
                        tags[tag] = max(tags.get(tag, 0), v)
                role = next((r for r in ['crosssection', 'opening', 'packaging', 'cutting'] if r in tags or (r == 'crosssection' and 'cream' in tags)), 'packaging')
                moving = [r['motion'] for r in rows[i:j + 1] if r.get('motion') is not None]
                vecs = [r['vec'] for r in rows[i:j + 1] if r.get('vec') is not None]
                shots.append({'asset_id': a['id'], 'start': start, 'end': end, 'role': role, 'lineup': False,
                              'product': labels[i], 'used': False, 'motion': sum(moving) / len(moving) if moving else None,
                              'vec': _unit_vec(sum(vecs)) if vecs else None})
            i = j + 1
        # 여러 제품을 한꺼번에 들어 보이는 순간(CLIP '비교' 태그) → 첫 장면 후보. 3초 안에 이어지면 한 장면.
        moments = []
        for r, label in zip(rows, labels):
            if 'comparison' in (r.get('tags') or {}) or label == MULTI:
                if moments and r['start'] - moments[-1][1] <= 3:
                    moments[-1][1] = r['end']
                else:
                    moments.append([r['start'], r['end']])
        motion = lambda m0, m1: ([r['motion'] for r in rows if m0 <= r['start'] <= m1 and r.get('motion') is not None] or [None])
        shots += [{'asset_id': a['id'], 'start': m0 - .5, 'end': m1 + .5, 'role': 'packaging', 'lineup': True,
                   'product': None, 'used': False, 'motion': min(motion(m0, m1), key=lambda x: (x is None, x))} for m0, m1 in moments]
    return sorted(shots, key=lambda s: (s['asset_id'], s['start']))


LOOK_GAP = 6.       # 같은 제품 디테일 컷끼리 최소 간격(초). 같은 상자를 같은 자세로 든 장면이 두 번 나오지 않게
LINEUP_GAP = 15.    # 제품 여러 개를 함께 든 컷끼리 최소 간격(초)
REPEAT_NEAR = 4.    # 이미 화면에 나온 원본 구간에서 이만큼 안쪽이면 같은 장면으로 본다
MAX_LOOKS = 3       # 제품 하나에 디테일 컷 최대 3개(1123: 앞면 → 연 상자 → 펼친 낱개). 더 쓰면 비슷한 장면이 반복된다


LOOK_SIM = .88      # 장면 그림 특징 유사도가 이 이상이면 같은 장면(1123 직접 편집본이 한 제품에 쓴 컷끼리는 최대 .85)


def _unit_vec(v):
    import numpy as np
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _apart(a, b, gap):
    if a.get('vec') is not None and b.get('vec') is not None and float(a['vec'] @ b['vec']) >= LOOK_SIM:
        return False   # 시간은 떨어져도 그림이 같은 장면(예: 펼친 낱개를 두 번)
    return a['asset_id'] != b['asset_id'] or a['start'] - b['end'] >= gap or b['start'] - a['end'] >= gap


def _spread(pool, k, gap):
    """후보 컷 k개를 촬영 순서 전체에 고르게 고른다(서로 gap초 이상 떨어지게).

    사용자 직접 편집본 1123(원본 011213과 대조): 제품마다 디테일 영상 구간 처음·가운데·끝에서 한 컷씩
    (소금우유 69~104초 구간 → 68.6·76.6·96.8초, 호지차 0~62초 → 16.6·28·51.8초) 앞면 → 연 상자 → 펼친 낱개 순으로 썼다.
    이전 자동 편집은 구간 앞쪽 컷만 연달아 골라 같은 상자 앞면이 2~3번 나왔다(사용자: '똑같은 장면이 2번 나와').
    """
    pool = sorted(pool, key=lambda s: (s['asset_id'], s['start']))
    picked = []
    for j in range(min(k, len(pool))):
        # 구간을 k등분해 각 칸에서 가장 덜 흔들린 장면(움직임 값이 없으면 칸 가운데)을 고른다
        lo, hi = j * len(pool) / k, (j + 1) * len(pool) / k
        want = (lo + hi) / 2
        def rank(i):
            inside = lo <= i + .5 <= hi
            m = pool[i].get('motion')
            return (not inside, round(m / .03) if inside and m is not None else 0, abs(i + .5 - want))
        for i in sorted(range(len(pool)), key=rank):
            if pool[i] not in picked and all(_apart(pool[i], q, gap) for q in picked):
                picked.append(pool[i])
                break
    return sorted(picked, key=lambda s: (s['asset_id'], s['start']))


def _detail_wants(kept):
    """디테일 컷을 얹을 발화를 제품별로 모은다(소개·설명·맛 평가 앞부분). 점수·결론·시식 직후 반응은 얼굴."""
    wants = {}
    for u, k in _product_blocks(kept):
        name = (u.get('product') or {}).get('name') or u.get('auto_product')
        labels = set(u['labels'])
        if not name or u.get('overlay') or u.get('after_bite') or u.get('montage') or labels & FACE_LABELS or not labels & DETAIL_LABELS:
            continue
        if u['end'] - u['start'] - .8 < DETAIL_SHOW[0]:
            continue
        wants.setdefault(name, []).append(u)
    return wants


def _storyboard(shots, names, wants, reserve=0):
    """제품마다 쓸 디테일 컷을 미리 정한다: 필요한 수(+첫 장면 자리)만큼 그 제품 촬영 구간 전체에 고르게."""
    story = {}
    for n in names:
        k = min(MAX_LOOKS, len(wants.get(n, [])) + reserve)
        by = {}
        for s in shots:
            if not s['lineup'] and s['product'] == n:
                by.setdefault(s['asset_id'], []).append(s)
        picked = []
        # 그 제품을 가장 오래 찍은 디테일 영상에서 먼저 고른다(1123: 제품별 컷은 전부 상자 하나씩 찍은 011213에서).
        for pool in sorted(by.values(), key=len, reverse=True):
            picked += _spread(pool, k - len(picked), LOOK_GAP)
        story[n] = picked
    return story


def _overlay_details(kept, shots, story=None):
    """제품 소개·설명·맛 평가 발화 앞부분에 같은 제품 디테일 컷 하나(0.8~1.4초)를 얹는다. 한 컷은 한 번만 쓴다."""
    wants = _detail_wants(kept)
    story = story if story is not None else _storyboard(shots, list(wants), wants)
    count = 0
    for name, units in wants.items():
        for u in units:
            looks = [s for s in story.get(name, []) if not s['used']]
            if not looks:
                break
            s = looks[0]
            take = min(DETAIL_SHOW[1], s['end'] - s['start'], u['end'] - u['start'] - .8)
            if take < DETAIL_SHOW[0]:
                continue
            mid = (s['start'] + s['end'] - take) / 2
            u['overlay'] = {'start': mid, 'end': mid + take, 'role': s['role'], 'asset_id': s['asset_id']}
            s['used'] = True
            count += 1
    return count


def _opening_slot(shots, order, fps=30, length=11., piece=.9, story=None):
    """후 나레이션 자리: 첫 약 10초(원본 기준 11초 = 1.3배속 후 약 8.5초)를 사용자 편집본 1123 첫 부분처럼 채운다.

    1123 첫 10초 실측: 제품 4개를 들고 있는 컷 → 제품별 상자 컷(테이블) → 단면 컷 → 다시 들고 있는 컷, 한 컷 0.3~1초(배속 후).
    소리는 각 컷 원본 소리(말 없음). 캡컷에서 후킹 나레이션을 녹음해 얹는다. 말하는 원본은 쓰지 않는다(첫 문장이 바로 나오지 않게).
    같은 장면은 두 번 쓰지 않는다: 여러 제품 컷은 촬영 시간 전체에서 15초 이상 떨어진 것, 단면 컷은 영상 하나에 하나,
    제품 상자 컷은 그 제품 디테일 컷 계획(story)의 첫 컷(뒤에 나오는 설명 컷과 다른 장면).
    """
    step = 1 / fps
    snap = lambda x: round(x / step) * step
    lineup = _spread([s for s in shots if s['lineup'] and not s['used']], 6 if length > 11 else 4, LINEUP_GAP)
    if story is None:
        story = _storyboard(shots, order, {}, 1)
    boxes = {n: v[0] for n, v in story.items() if v and not v[0]['used']}
    cuts, seen = [], set()
    for s in sorted((s for s in shots if not s['used'] and not s['lineup'] and s['role'] == 'crosssection'), key=lambda s: (s['asset_id'], s['start'])):
        if s['asset_id'] not in seen and not any(s is v for vs in story.values() for v in vs):
            same = [c for c in shots if c['asset_id'] == s['asset_id'] and c['role'] == 'crosssection' and not c['lineup'] and not c['used']]
            mid = len(same) // 2   # 움직임 값이 없으면 단면 영상 가운데(자르는 손이 지나간 뒤 단면이 보이는 쪽)
            cuts.append(min(same, key=lambda c: (c.get('motion') is None, c.get('motion') or 0, abs(same.index(c) - mid))))   # 가장 덜 흔들린 단면 컷
            seen.add(s['asset_id'])
    picked = lineup[:2] + [boxes[n] for n in order if n in boxes] + cuts[:2] + lineup[2:]
    # 콘티 나레이션이 길면(1122 콘티 첫 세 줄 ≈ 10초) 컷을 늘리고, 그래도 모자라면 한 컷을 1.5초까지 길게 쓴다.
    piece = min(1.5, max(piece, length / max(1, len(picked))))
    units, total = [], 0.
    for s in picked:
        take = min(piece, s['end'] - s['start'], length - total)
        if take < .5:
            continue
        a = snap((s['start'] + s['end'] - take) / 2)
        units.append({'kind': 'visual', 'asset_id': s['asset_id'], 'filename': '', 'start': a, 'end': snap(a + take),
                      'role': s['role'], 'labels': [s['role']], 'visual_roles': [s['role']], 'text': '', 'review': ['후 나레이션 자리 · 캡컷에서 녹음'],
                      'drop': None, 'opening_slot': True})
        s['used'] = True
        total += take
        if total >= length - .5:
            break
    if units and total < length - .5:
        # 아직 나레이션보다 짧으면 앞에 쓴 컷과 다른 장면(6초 이상·그림 다름)의 단면·제품 모아 보여 주기 컷을 더 잇는다.
        chosen = [s for s in picked if s['used']]
        reserved = [v for vs in story.values() for v in vs]
        pool = [s for s in shots if not s['used'] and (s['lineup'] or s['role'] == 'crosssection')
                and not any(s is v for v in reserved) and all(_apart(s, c, LOOK_GAP) for c in chosen)]
        for s in _spread(pool, int((length - total) / piece) + 1, LOOK_GAP):
            take = min(piece, s['end'] - s['start'], length - total)
            if take < .5 or not all(_apart(s, c, LOOK_GAP) for c in chosen):
                continue
            a = snap((s['start'] + s['end'] - take) / 2)
            units.insert(len(units) - min(2, len(units) // 3), {   # 마지막 '다시 들고 있는 컷' 앞에 넣는다
                'kind': 'visual', 'asset_id': s['asset_id'], 'filename': '', 'start': a, 'end': snap(a + take),
                'role': s['role'], 'labels': [s['role']], 'visual_roles': [s['role']], 'text': '', 'review': ['후 나레이션 자리 · 캡컷에서 녹음'],
                'drop': None, 'opening_slot': True})
            s['used'] = True
            chosen.append(s)
            total += take
            if total >= length - .5:
                break
    return units if len(units) >= 3 else []


def _drop_repeats(kept):
    """같은 원본 장면이 두 번 보이지 않게, 얹은 화면(시식·디테일·단면) 중 이미 보인 화면 구간 근처(4초)는 뺀다(얼굴 화면으로 둔다).

    예시 영상 피드백(2026-11-23 '똑같은 장면이 2번 나와'): 1028초 먹는 화면을 한 번 얹고, 뒤에서 1024초 먹는 화면을
    또 얹었다. 화면에 나오는 원본 구간을 모두 모아, 앞에서 이미 나온 장면과 4초 안쪽이면 다시 얹지 않는다.
    """
    # 얹은 화면과 겹치는 단독 화면 구간(디테일 영상이 따로 남은 것)은 뺀다: 얹은 쪽이 제품 설명과 맞춰져 있다.
    laid = [(u['overlay'].get('asset_id', u['asset_id']), u['overlay']['start'], u['overlay']['end']) for u in kept if u.get('overlay')]
    laid += [(u['asset_id'], u['start'], u['end']) for u in kept if u.get('opening_slot')]
    kept[:] = [u for u in kept if u['kind'] != 'visual' or u.get('opening_slot')
               or not any(a == u['asset_id'] and u['start'] < y and u['end'] > x for a, x, y in laid)]
    # 말하는 얼굴 화면(원래 화면)은 비교하지 않는다: 먹고 나서 바로 말하는 장면은 같은 카메라가 이어진 것이다.
    shown = [(u['asset_id'], u['start'], u['end']) for u in kept if u['kind'] == 'visual']
    for u in kept:
        for p in u.get('montage') or []:
            shown.append((p[4] if len(p) > 4 else u['asset_id'], p[2], p[2] + p[1] - p[0]))
    dropped = 0
    for u in kept:
        o = u.get('overlay')
        if not o or o.get('asset_id', u['asset_id']) == u['asset_id']:
            continue   # 말하는 원본의 먹는 화면은 빼지 않는다(사용자: '먹방 모습이 사라짐'. 직접 편집본도 1135초 먹는 화면을 두 번 썼다)
        aid = o['asset_id']
        if any(a == aid and o['start'] - y < REPEAT_NEAR and x - o['end'] < REPEAT_NEAR for a, x, y in shown):
            u.pop('overlay')
            dropped += 1
            continue
        shown.append((aid, o['start'], o['end']))
    return dropped


def _opening_lineup(hook, shots, fps=30, piece=(.8, 1.2)):
    """첫 멘트 아래 제품 포장·들어 보이기 컷을 0.8~1.2초씩 잇는다(얼굴은 첫 멘트 끝 0.6초에 돌아온다).

    완성본 1123: 첫 10초가 제품 4종을 들어 보이는 컷과 포장 컷(0.5~1.5초)이었고, 이전 자동 편집처럼 같은 단어를
    0.28초 조각으로 쪼개 화면만 바꾸는 방식은 없었다(사용자: '초반에 왜 그럼').
    """
    length = hook['end'] - hook['start'] - .6
    if length < 2 * piece[0]:
        return []
    # 첫 멘트는 보통 특정 제품 이야기라, 여러 제품을 함께 들어 보이는 컷만 쓴다(한 제품 포장 컷은 다른 제품을 말할 때 섞일 수 있음).
    picked = _spread([s for s in shots if not s['used'] and s['lineup']], 6, LINEUP_GAP)   # 같은 순간을 두 번 쓰지 않게
    step = 1 / fps
    snap = lambda x: round(x / step) * step
    pieces, t = [], snap(hook['start'])
    for s in picked:
        room = hook['start'] + length - t
        if room < piece[0]:
            break
        take = min(piece[1], s['end'] - s['start'], room)
        if take < piece[0]:
            continue
        end = snap(t + take)
        v0 = (s['start'] + s['end'] - (end - t)) / 2
        pieces.append((t, end, v0, s['role'], s['asset_id']))
        s['used'] = True
        t = end
    return pieces if len(pieces) >= 2 else []


def overlay_eating(kept, window=240., extra=()):
    """맛 평가 발화 위에 가까운 '말 없는 시식·단면 컷'을 화면으로 얹는다(소리는 발화 그대로).

    완성본 1116을 원본과 대조한 결과: 소리 컷 60개 중 28개가 이 방식(먹는 화면 + 나중에 말한 평가 소리)이었고,
    그중 22개는 화면이 소리보다 앞선 장면(중앙값 105초 전, 최대 147초 전)이며 화면도 촬영 순서대로 이어졌다.
    완성본 화면은 원본을 좌우반전한 상태였다(자동 적용하지 않음).
    제품을 들어 보이며 소개하는 말, 점수("N점 드릴게요"), 결론은 얼굴이 보이는 원래 화면을 그대로 쓴다.
    얹는 데 쓴 시식 컷은 단독 구간으로는 넣지 않는다(같은 장면이 두 번 나오지 않게).
    """
    pool = [{'unit': u, 'cursor': u['start']} for u in kept if u['kind'] == 'visual' and u['role'] in OVERLAY_ROLES and not u.get('bite')]
    # 말없는 먹는 구간에서 고른 먹방 순간(한입·단면 보여 주기). 시식 나레이션(첫 소감 위 한입 화면)과 겹치거나 이미 있는 화면은 빼고.
    taken = [(u['asset_id'], u['overlay']['start'], u['overlay']['end']) for u in kept if u.get('overlay')] + \
            [(u['asset_id'], u['start'], u['end']) for u in kept if u['kind'] == 'visual']
    pool += [{'unit': m, 'cursor': m['start']} for m in extra
             if not any(a == m['asset_id'] and m['start'] - y < 2 and x - m['end'] < 2 for a, x, y in taken)]
    used, count = set(), 0
    # 점수("N점 드릴게요")가 나오면 다음 제품이다. 점수를 건너뛴 화면은 다른 제품이라 쓰지 않는다
    # (예시 영상 피드백 '완전 딴 장면': 소금우유 소감 위에 점수 뒤 허니페어 개봉 화면이 얹혔다).
    scores = {}
    for u in kept:
        if u['kind'] == 'speech' and 'score' in u['labels']:
            scores.setdefault(u['asset_id'], []).append(u.get('speech_start', u['start']))
    intros = {}
    for u in kept:
        if u['kind'] == 'speech' and set(u['labels']) & INTRO_LABELS:
            intros.setdefault(u['asset_id'], []).append(u.get('speech_start', u['start']))
    def same_product(asset_id, a, b):
        lo, hi = min(a, b), max(a, b)
        if any(lo < t < hi for t in scores.get(asset_id, [])):
            return False
        if len(scores.get(asset_id, [])) < 2:
            return True
        # 여러 제품 영상: 점수와 다음 제품 소개 사이(다음 제품을 미리 뜯는 등)는 어느 제품인지 모른다.
        # 화면은 이 제품을 소개한 말 이후 것만 쓴다(1122 원본 359초: 호지차 소개 전 허니페어 개봉 화면).
        last = max([t for t in scores[asset_id] if t <= lo] + [-1.])
        first = min([t for t in intros.get(asset_id, []) if t > last] + [float('inf')])
        return lo >= first - 1
    wraps = 0
    for s in sorted((u for u in kept if u['kind'] == 'speech'), key=lambda u: (u['asset_id'], u['start'])):
        labels = set(s['labels'])
        # 전체 총평(마지막 점수 뒤)도 한 줄 걸러 먹는 화면을 얹는다(직접 편집본 1123: 총평 1158~1224초 말 위에 1188·1197·1210초 먹는 화면).
        # 총평은 네 제품 전체 이야기라 제품 경계를 따지지 않는다.
        wrap = 'wrapup' in labels and 'score' not in labels and not s.get('after_bite')
        if wrap:
            wraps += 1
            if wraps % 2 == 0:
                continue
        elif s.get('after_bite') or not labels & {'taste', 'pro', 'con'} or labels & {'score', 'conclusion', 'repurchase', 'intro', 'describe', 'compare'}:
            continue
        name = (s.get('product') or {}).get('name')
        best = None
        for p in pool:
            v = p['unit']
            if v['asset_id'] != s['asset_id'] or v['end'] - p['cursor'] < .6:
                continue
            other = (v.get('product') or {}).get('name')
            if not wrap and name and other and name != other:
                continue
            if not wrap and not same_product(s['asset_id'], p['cursor'], s['speech_start'] if 'speech_start' in s else s['start']):
                continue
            gap = s['start'] - v['end'] if v['end'] <= s['start'] else (v['start'] - s['end']) * 4 + 1   # 먹고 나서 말한 경우를 우선
            rank = (not v.get('eating_moment'), gap)   # 먹는 구간에서 고른 한입·단면 보여 주기 순간을 먼저(직접 편집본 방식)
            if 0 <= gap <= window and (best is None or rank < best[0]):
                best = (rank, p)
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


def _cut_pauses(kept):
    """문장 안 쉼을 잘라 조각으로 나눈다. 화면을 얹은(시식 컷) 문장은 화면도 조각 길이만큼 이어서 나눈다."""
    out = []
    for u in kept:
        pieces, t = [], u['start']
        if not u.get('montage'):   # 후킹 몽타주는 소리 기준으로 화면이 짜여 있어 그대로 둔다
            for c0, c1 in u.get('pauses', []):
                if t < c0 < c1 < u['end']:
                    pieces.append((t, c0))
                    t = c1
        pieces.append((t, u['end']))
        if len(pieces) == 1:
            out.append(u)
            continue
        over, used = u.get('overlay'), 0.
        for k, (a, b) in enumerate(pieces):
            piece = {**u, 'start': a, 'end': b, 'pauses': [], 'piece': k}
            if over:
                v0 = over['start'] + used
                piece['overlay'] = {**over, 'start': v0, 'end': min(over['end'], v0 + b - a)} if over['end'] - v0 >= .3 else None
                used += b - a
            out.append(piece)
    return out


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
            for a0, a1, v0, role, *vid in u['montage']:
                clips.append({'asset_id': u['asset_id'], 'start': a0, 'end': a1, 'frame': frame,
                              'visual_asset_id': vid[0] if vid else u['asset_id'], 'visual_start': v0, 'visual_end': v0 + (a1 - a0),
                              'guided': {'units': [{**_brief(u), 'reason': '첫 장면 · 화면은 ' + ROLE_LABEL.get(role, role) + ' 컷'}]}})
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
                          'visual_asset_id': over.get('asset_id', u['asset_id']), 'visual_start': over['start'], 'visual_end': over['end'],
                          'guided': {'units': [{**_brief(u), 'reason': _reason(u) + (' · 먹는 화면 위 소감 나레이션' if over.get('narration') else f' · 화면은 {ROLE_LABEL.get(over["role"], over["role"])} 컷')}]}})
            cur = None if whole else {'asset_id': u['asset_id'], 'start': split, 'end': u['end'], 'frame': frame,
                                      'guided': {'units': [_brief(u)]}}
            continue
        # 문장 사이 0.3초 미만 공백은 이어 붙여 자연스럽게(말 위주 편집·같은 문장의 쉼 조각은 이어 붙이지 않는다).
        join = .04 if rules.get('tight') or u.get('piece') else .3
        if cur and not cur.get('visual_asset_id') and cur['asset_id'] == u['asset_id'] and 0 <= u['start'] - cur['end'] < join:
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
        prev = out[-1] if out else None
        c['id'] = f'guided-{i:03}'
        c['label'] = f'{i}. {first["role_label"]}' + (f' · {first["text"][:30]}' if first['text'] else '')
        c['start'] = max(0., math.floor(c['start'] * fps + 1e-6) / fps)
        c['end'] = max(c['start'] + 1 / fps, math.ceil(c['end'] * fps - 1e-6) / fps)
        c['end'] = min(c['end'], math.floor(meta[c['asset_id']]['metadata']['duration'] * fps) / fps)
        if prev and prev['asset_id'] == c['asset_id'] and prev['start'] < c['start'] < prev['end'] + 1e-6:
            # 프레임 맞춤(시작 내림·끝 올림) 때문에 바로 이어지는 두 클립이 1프레임 겹치면 같은 소리가 두 번 난다.
            shift = prev['end'] - c['start']
            c['start'] = prev['end']
            if c.get('visual_asset_id'):
                c['visual_start'] += shift
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
