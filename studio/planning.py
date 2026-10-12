"""Food shorts guide as a local, editable planning workflow; no fabricated research."""
import copy
import re
from datetime import date
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from . import proofreading, timeline

RUBRICS = [
    ['대중적 관심', '검증할 의문', '볼거리', '차별성', '제작 가능성'],
    ['즉시 이해', '의문의 강도', '구체성', '첫 화면과 결합', '본편에서 답할 수 있음'],
    ['후킹의 답', '다음 장면을 볼 이유', '나만의 시각', '말의 흐름·중복 최소화', '분량·촬영 가능성'],
    ['질문', '시청 이유', '고유 관점', '장면·결론', '확인 사항의 명확성'],
    ['즉시 이해', '호기심', '구체성', '서로 보완', '본편과 일치'],
    ['간결함', '실제 평가', '정보 정확성', '짧은 CTA', '조건·표기 반영'],
]
HEADINGS = ['소재의 장점·단점', '추천 후킹', '영상 구성안', '핵심 요약', '썸네일·제목', '캡션 요약']


class Fact(BaseModel):
    kind: str = Field(default='제품 정보', max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    source: str = 'user'
    url: str = Field(default='', max_length=2000)
    checked_on: str = Field(default='', max_length=10)
    conditions: str = Field(default='', max_length=1000)

    @field_validator('source')
    @classmethod
    def source_valid(cls, value):
        if value not in ['user', 'external', 'assumption']:
            raise ValueError('사실 구분은 user, external, assumption 중 하나입니다.')
        return value

    @field_validator('url')
    @classmethod
    def url_valid(cls, value):
        if value and (urlparse(value).scheme not in ['http', 'https'] or not urlparse(value).hostname):
            raise ValueError('출처는 HTTP 또는 HTTPS 주소로 입력해 주세요.')
        return value

    @field_validator('checked_on')
    @classmethod
    def date_valid(cls, value):
        if value:
            date.fromisoformat(value)
        return value


class Brief(BaseModel):
    subject: str = Field(min_length=1, max_length=150)
    kind: str = 'single'
    target_seconds: int | None = Field(default=None, ge=5, le=1800)
    platform: str = Field(default='쇼츠·릴스', max_length=100)
    question: str = Field(default='', max_length=300)
    facts: list[Fact] = Field(default_factory=list, max_length=50)
    taste: str = Field(default='', max_length=3000)
    conclusion: str = Field(default='', max_length=1000)
    motive: str = Field(default='', max_length=1000)
    criteria: str = Field(default='', max_length=1000)
    footage: str = Field(default='', max_length=3000)
    budget: str = Field(default='', max_length=500)
    sponsorship: str = Field(default='', max_length=1000)
    locked_script: str = Field(default='', max_length=10000)
    corrections: str = Field(default='', max_length=10000)

    @field_validator('kind')
    @classmethod
    def kind_valid(cls, value):
        if value not in ['single', 'comparison', 'list', 'experiment', 'cooking']:
            raise ValueError('콘텐츠 유형을 확인해 주세요.')
        return value


def fact_status(fact):
    if fact.source == 'assumption':
        return '가정 · 멘트에 사용하지 않음'
    if fact.source == 'external':
        return ('사용자 출처 확인 · 서버 원문 미조회' if fact.url and fact.checked_on and fact.conditions
                else '확인 필요 · 출처·기준일·조건 보완')
    return '사용자 제공 사실 · 외부 검증 전'


def score(index, values, evidence, improvement):
    criteria = [{'criterion': key, 'points': value} for key, value in zip(RUBRICS[index], values)]
    missing = [c['criterion'] for c in criteria if c['points'] < 2]
    return {'total': sum(values), 'criteria': criteria, 'provisional': True,
            'evidence': evidence, 'deduction': ' / '.join(missing) + ' 확인 전' if missing else '실제 촬영·낭독 검증 전',
            'improvement': improvement}


def build(brief):
    b = brief
    length = b.target_seconds or (60 if b.kind in ['comparison', 'list'] else 30 if b.kind == 'cooking' else 18)
    name = b.subject.strip()
    question = b.question.strip() or f'{name}, 내 기준에 맞을까?'
    if not question.endswith(('?', '？')):
        question += '?'
    # External statements are never incorporated as confirmed facts by this template engine.
    provided = [f for f in b.facts if f.source == 'user']
    conditions = [{'kind': f.kind, 'text': f.text, 'status': fact_status(f), 'url': f.url,
                   'checked_on': f.checked_on, 'conditions': f.conditions} for f in b.facts]
    price = next((f for f in provided if '가격' in f.kind or '구매가' in f.kind), None)
    claim = next((f for f in provided if '주장' in f.kind or '표기' in f.kind), None)
    info = ' / '.join(f'{f.kind}: {f.text}' + (f' ({f.conditions})' if f.conditions else '') for f in provided[:2])
    hooks = [
        {'angle': '맛·평가 기준', 'caption': '내 기준에 맞는 맛일까?', 'voice': question,
         'shot': '제품·단면을 가까이 촬영한 첫 1~3초', 'elements': ['질문 던지기'],
         'condition': '질문의 구체적인 이유와 실제 시식 컷을 확보해 주세요.',
         'score': score(1, [1, 1, 2 if b.question else 0, 1, 2 if b.taste else 0],
                        '입력한 질문과 제품 단면을 연결합니다.', '의문이 생긴 실제 이유를 질문에 담아 주세요.')},
        {'angle': '가격·구매 가치', 'caption': '이 가격에 먹을 만할까?',
         'voice': f'{price.text}인데, 이 가격에 먹을 만할까?' if price else '[확인된 구매가]인데, 이 가격에 먹을 만할까?',
         'shot': '제품과 실제 가격표·영수증을 함께 촬영한 첫 1~3초', 'elements': ['질문 던지기'],
         'condition': '용량·수량·할인·배송비·구매일을 확인하고 가치 판단을 실제로 촬영해 주세요.',
         'score': score(1, [2, 1, 2 if price and price.conditions else 0, 1, 2 if b.conclusion else 0],
                        '제공된 구매가를 사용합니다.' if price else '구매가가 아직 없습니다.', '가격과 구매 조건을 채워 주세요.')},
        {'angle': '표기·비주얼 검증', 'caption': '이 단면, 실제로는 어떨까?',
         'voice': f'표기에는 {claim.text}. 실제로도 그럴까?' if claim else '[실제로 확인할 제품 표기], 그대로일까?',
         'shot': '실제 패키지 표기와 실제 단면을 한 화면에 배치한 첫 1~3초', 'elements': ['질문 던지기'],
         'condition': '표기 원문과 검증 가능한 실제 단면을 확보해 주세요. 없으면 사용하지 마세요.',
         'score': score(1, [1, 1, 2 if claim else 0, 1, 2 if claim and b.taste else 0],
                        '패키지의 실제 주장과 시식 결과를 대조하는 후보입니다.', '검증할 실제 표기나 비주얼을 입력해 주세요.')},
    ]
    chosen = max(range(3), key=lambda i: hooks[i]['score']['total'])
    hook = hooks[chosen]
    # First build all recording lines, then split those same lines into the storyboard.
    script_lines = [hook['voice'],
                    f'고른 이유는 {b.motive.strip() or "[고른 실제 이유]"}이고, 확인할 기준은 {b.criteria.strip() or "[내 평가 기준]"}입니다.' +
                    (f' 확인한 제품 정보는 {info}입니다.' if info else ' [확인한 제품 정보]'),
                    b.taste.strip() or '[실제 맛 반응]',
                    b.conclusion.strip() or '[시식 후 결정]',
                    '여러분은 먹어보셨나요?']
    roles = ['궁금증', '필요한 정보 · 나의 관점', '시식·비교·검증 · 내 기준', '질문의 답 · 구매 판단', '댓글 질문 1개']
    shots = [hook['shot'], '제품 패키지·정보와 선택 이유', '실제 한입·단면·비교 컷', '판단 근거가 보이는 제품 컷', '마지막 제품 컷']
    script = ' '.join(script_lines)
    if b.locked_script.strip():
        # Finalized text, numbers, line breaks and endings are preserved byte-for-byte.
        script = b.locked_script
        script_lines = b.locked_script.splitlines(keepends=True)
        roles = ['확정 대본 · 직접 역할 확인'] * len(script_lines)
        shots = ['확정 대사에 맞는 실제 촬영 구간을 연결해 주세요.'] * len(script_lines)
    weights = [max(1, len(re.sub(r'\s+', '', line))) for line in script_lines]
    total_weight = sum(weights)
    scenes, cursor = [], 0.
    for i, (line, role, shot) in enumerate(zip(script_lines, roles, shots)):
        end = float(length) if i == len(script_lines) - 1 else round(cursor + length * weights[i] / total_weight, 2)
        scenes.append({'id': f'scene-{i + 1}', 'start': cursor, 'end': end, 'shot': shot,
                       'voice': line, 'caption': hook['caption'] if i == 0 and not b.locked_script else line.strip(),
                       'role': role, 'mandatory': True, 'asset_id': '', 'source_start': 0, 'source_end': 0})
        cursor = end
    thumbnails = [
        {'text': hook['caption'], 'image': '실제 단면을 크게, 패키지를 작은 크기로 배치'},
        {'text': '이 가격이면 살까?', 'image': '제품 옆에 확인한 가격표·영수증 배치 · 가격 미확인 시 사용 보류'},
        {'text': '표기와 실제 단면', 'image': '실제 패키지 표기와 실제 단면을 좌우에 배치 · 두 컷 확보 필요'},
    ]
    titles = [f'{name}, {b.criteria.strip() or "내 기준"}으로 직접 확인할 질문',
              f'{name}, 가격 대비 먹을 만할까?', f'{name}, 표기와 실제 단면을 비교하면?',
              f'{name}, 한입 먹고 확인할 포인트', f'{name}, 구매 전에 무엇을 봐야 할까?']
    price_line = f'{price.text} ({price.conditions or "[용량·수량·구매일·할인·배송비 조건]"})' if price else '[구매가 · 용량·수량·구매일·할인·배송비 조건]'
    store = next((f.text for f in provided if '판매처' in f.kind or '구매처' in f.kind), '[구매처]')
    post = f'{question} {b.taste.strip() or "[시식 후 평가]"}\n{name} · {price_line} · {store}\n여러분은 먹어보셨나요?\n#푸드리뷰 #음식리뷰 #리뷰하는이요링'
    if b.sponsorship.strip():
        post += '\n' + b.sponsorship.strip()
    evidence = '사용자 제공 자료만 반영한 초안입니다. 출처 원문과 실제 낭독·촬영은 검증하지 않았습니다.'
    scores = [
        score(0, [0, 2 if b.question else 0, 1 if b.footage else 0, 1 if b.criteria else 0, 1 if b.budget and b.footage else 0], evidence, '실제 차이가 드러나는 단면·비교 컷을 확보해 주세요.'),
        hook['score'],
        score(2, [2 if b.conclusion else 0, 1, 1 if b.motive and b.criteria else 0, 1, 1 if b.footage else 0], evidence, '전체 대본을 낭독하고 실제 컷 길이에 맞춰 중복 설명을 덜어 주세요.'),
        score(3, [2 if b.question else 1, 1, 1 if b.criteria else 0, 1 if b.taste else 0, 2], evidence, '실제 결론과 고유 평가 기준을 채워 주세요.'),
        score(4, [2, 1, 1, 1, 1], evidence, '본편에서 답할 수 있는 질문과 실제 이미지로 조합을 검증해 주세요.'),
        score(5, [1 if len(post) > 400 else 2, 2 if b.taste else 0, 1 if provided else 0, 2, 1 if price and price.conditions else 0], evidence, '실제 시식 평가와 구매 조건을 확인해 주세요.'),
    ]
    checklist = [
        '출처 링크는 저장만 합니다. 서버가 웹 원문이나 사실 여부를 자동 검증하지 않습니다.',
        '가격·랭킹·유행·출시일은 1차 출처, 기준일, 용량·수량·할인 등 조건을 확인해 주세요.',
        '후킹·썸네일·제목의 약속이 본편의 실제 촬영 결과와 일치하는지 확인해 주세요.',
        '시간은 낭독 전 예상치입니다. 실제 원본 구간을 연결하면 영상 길이를 별도로 계산합니다.',
        '인사·개봉은 줄일 수 있는 선택 컷입니다. 단순 씹는 장면은 약 5초, 조리 설명은 약 30초를 기준으로 직접 검토해 주세요.',
        '미정 평가·동기·기준의 빈칸은 실제 경험으로 채워 주세요. 조회수나 성공 확률을 보장하지 않습니다.',
    ]
    if b.locked_script:
        checklist.append('확정 대본은 입력 그대로 보존했습니다. 지침과 충돌하는 부분은 제안만 검토해 주세요.')
    return {'version': 1, 'engine': '지침 기반 템플릿 초안 · 외부 AI·웹 검색 없음', 'brief': b.model_dump(),
            'target_seconds': length, 'estimated': True, 'script': script, 'script_separator': '' if b.locked_script else ' ',
            'scenes': scenes, 'hooks': hooks, 'chosen_hook': chosen,
            'hook_reason': '현재 입력에서 가장 많은 근거를 가진 후보입니다. 빠진 사실과 촬영 조건을 채운 뒤 확정해 주세요.',
            'subject': {'decision': '조건부 추천' if b.question or b.footage else '우선순위 낮음',
                        'pros': [f'{name}의 실제 단면·맛을 질문에 연결할 수 있습니다.', '내 평가 기준이 있다면 구매 판단을 비교할 수 있습니다.'],
                        'cons': ['유행·대중적 관심은 확인되지 않았습니다.', '시식 결과와 촬영 가능성에 따라 결론·분량이 달라집니다.'],
                        'point': question, 'fix': '질문이 생긴 실제 이유와 답을 보여줄 컷부터 확보해 주세요.'},
            'perspective': f'{b.criteria or "[내 평가 기준]"}으로 판단하는 과정을 보여주는 것이 이 이야기를 들을 이유입니다.',
            'summary': [question, f'실제 시식 과정에서 답을 확인합니다. 마지막 질문: 여러분은 먹어보셨나요?',
                        f'관점: {b.criteria or "[내 평가 기준]"}', '필수 컷: 제품·단면·시식·판단 근거',
                        f'결론: {b.conclusion or "[시식 후 결정]"}', '확인: 출처·기준일·구매 조건·협찬 여부'],
            'thumbnails': thumbnails, 'titles': titles, 'pair': {'thumbnail': 0, 'title': 0,
                'reason': '단면 질문과 제품명·평가 기준을 서로 보완합니다. 실제 답이 있는지 촬영 후 확인해 주세요.', 'score': scores[4]},
            'post_caption': post, 'facts': conditions, 'scores': scores, 'checklist': checklist,
            'weakest': min(range(6), key=lambda i: scores[i]['total']),
            'goal': '100만 목표의 강점은 질문과 실제 검증의 연결입니다. 대중적 관심·촬영 완성도·시청 지속은 확인 전이며, 점수는 조회수 예측이 아닙니다.'}


def script_from_scenes(plan):
    return plan.get('script_separator', ' ').join(scene['voice'] for scene in plan['scenes'])


def validate_plan(plan):
    try:
        Brief.model_validate(plan['brief'])
        if not isinstance(plan['scenes'], list) or not 1 <= len(plan['scenes']) <= 1000:
            raise ValueError('기획 장면은 1~1,000개까지 지원합니다.')
        seen = set()
        for scene in plan['scenes']:
            if not isinstance(scene['id'], str) or scene['id'] in seen:
                raise ValueError('기획 장면 ID를 확인해 주세요.')
            seen.add(scene['id'])
            for key in ['voice', 'caption', 'shot', 'role']:
                if not isinstance(scene[key], str) or len(scene[key]) > 10000:
                    raise ValueError('기획 장면 문구를 확인해 주세요.')
            for key in ['start', 'end', 'source_start', 'source_end']:
                if not timeline.finite(scene[key]) or scene[key] < 0:
                    raise ValueError('기획 장면 시간을 확인해 주세요.')
        if plan.get('script_separator', ' ') not in ['', ' ']:
            raise ValueError('대본 연결 형식을 확인해 주세요.')
        if not isinstance(plan['target_seconds'], int) or not 5 <= plan['target_seconds'] <= 1800:
            raise ValueError('기획 목표 길이를 확인해 주세요.')
        if len(plan['hooks']) != 3 or len(plan['thumbnails']) != 3 or len(plan['titles']) != 5 or len(plan['scores']) != 6:
            raise ValueError('지침의 기획 항목 수를 확인해 주세요.')
        if plan['chosen_hook'] not in [0, 1, 2] or plan['weakest'] not in range(6):
            raise ValueError('기획 선택 항목을 확인해 주세요.')
        if len(plan['summary']) > 6:
            raise ValueError('핵심 요약은 최대 6줄입니다.')
        for fact in plan['facts']:
            Fact.model_validate({**fact, 'source': 'user'})
        plan['script'] = script_from_scenes(plan)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('기획 정보 형식을 확인해 주세요.') from exc
    return plan


def audit(plan, corrections=''):
    fields = [('게시 캡션', plan.get('post_caption', ''), 'post_caption')]
    fields += [(f'장면 {i + 1} 멘트', s['voice'], f'scenes.{i}.voice') for i, s in enumerate(plan['scenes'])]
    fields += [(f'장면 {i + 1} 자막', s['caption'], f'scenes.{i}.caption') for i, s in enumerate(plan['scenes'])]
    fields += [(f'후킹 {i + 1}', h['voice'], f'hooks.{i}.voice') for i, h in enumerate(plan.get('hooks', []))]
    fields += [(f'후킹 {i + 1} 자막', h['caption'], f'hooks.{i}.caption') for i, h in enumerate(plan.get('hooks', []))]
    fields += [(f'제목 {i + 1}', title, f'titles.{i}') for i, title in enumerate(plan.get('titles', []))]
    fields += [(f'썸네일 {i + 1}', t['text'], f'thumbnails.{i}.text') for i, t in enumerate(plan.get('thumbnails', []))]
    results = [{'field': name, 'path': path, **proofreading.inspect_text(text, corrections)} for name, text, path in fields]
    script = script_from_scenes(plan)
    checks = []
    if len(re.findall(r'요[.!?。]?\s', script + ' ')) >= 3:
        checks.append('요 종결이 반복됩니다. 확정 대본은 보존하고 연결 어미 수정안을 검토해 주세요.')
    if script.count('?') > 2:
        checks.append('질문이 많습니다. 후킹 1개와 마지막 댓글 질문 1개에 집중해 주세요.')
    if re.search(r'구독|좋아요', plan['scenes'][-1]['voice']):
        checks.append('마지막 CTA는 구독·좋아요 요청 없이 짧은 댓글 질문 1개를 권장합니다.')
    if len(re.sub(r'\s', '', script)) / 5 > plan['target_seconds']:
        checks.append('초당 5글자 기준으로 목표 분량을 넘을 수 있습니다. 실제 낭독 후 조정해 주세요.')
    if any(f.get('status', '').startswith('확인 필요') for f in plan.get('facts', [])):
        checks.append('외부 사실의 출처·기준일·조건이 빠져 있습니다.')
    return {'fields': results, 'checks': checks, 'notice': '규칙 기반 검토와 실제 자료 대조가 함께 필요합니다. 확정 원문은 자동 수정하지 않습니다.'}


def apply_storyboard(state, plan, assets):
    scenes = plan.get('scenes', [])
    if not scenes or len(scenes) > 3000:
        raise ValueError('연결할 장면이 없습니다.')
    clips = []
    for scene in scenes:
        if not scene.get('asset_id'):
            raise ValueError('모든 필수 장면에 실제 원본 구간을 연결해 주세요.')
        clips.append({'id': f'plan-{scene["id"]}', 'asset_id': scene['asset_id'],
                      'start': scene.get('source_start'), 'end': scene.get('source_end'),
                      'label': scene.get('role', '기획 장면'), 'frame': {'mode': 'fit', 'x': .5, 'y': .5, 'zoom': 1}})
    value = copy.deepcopy(state)
    value['clips'] = clips
    timeline.validate_state(value, assets)
    timeline.export_groups(value, 'full')
    # A planned voiceover is not a transcript of uploaded footage. Never inject it as recognized speech.
    value['planning'] = copy.deepcopy(plan)
    value['planning']['script'] = script_from_scenes(plan)
    value['planning']['actual_seconds'] = round(timeline.duration(clips), 3)
    value['cut_removals'] = []
    return value


def markdown(plan):
    def rating(s):
        details = ' / '.join(f'{c["criterion"]} {c["points"]}' for c in s['criteria'])
        return f'\n잠정 {s["total"]}/10 ({details}) → {s["evidence"]} → 감점: {s["deduction"]} → 개선: {s["improvement"]}\n'
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', '<br>')
    lines = [f'# {plan["brief"]["subject"]} 숏폼 기획', plan['engine'],
             f'목표 {plan["target_seconds"]}초 · 낭독 전 예상 · 실제 구간 {plan.get("actual_seconds", "연결 전")}초']
    for index, heading in enumerate(HEADINGS):
        lines += [f'\n## {index + 1}) {heading}\n']
        if index == 0:
            subject = plan['subject']
            lines += [subject['decision'], '장점: ' + ' / '.join(subject['pros']), '단점: ' + ' / '.join(subject['cons']),
                      '관전 포인트: ' + subject['point'], '보완: ' + subject['fix']]
        elif index == 1:
            for i, hook in enumerate(plan['hooks']):
                lines += [f'{i + 1}. {hook["angle"]} · 자막: {hook["caption"]}', f'멘트: {hook["voice"]}',
                          '첫 화면: ' + hook['shot'], '조건: ' + hook['condition'], '요소: ' + ', '.join(hook['elements']), rating(hook['score'])]
            lines += [f'선택: {plan["chosen_hook"] + 1}번. ' + plan['hook_reason']]
        elif index == 2:
            lines += ['| 예상 시간(초) | 필수 장면 | 멘트 | 자막 | 역할 |', '|---|---|---|---|---|']
            for s in plan['scenes']:
                lines.append('| ' + ' | '.join(map(cell, [f'{s["start"]}–{s["end"]}', s['shot'], s['voice'], s['caption'], s['role']])) + ' |')
            lines += ['내 이야기를 들을 이유: ' + plan['perspective'], '\n대본 합친 버전:\n', script_from_scenes(plan),
                      '\n선택·축소 컷: 인사·개봉·조리 설명·단순 씹는 장면. 실제 시식 설명은 유지합니다.']
        elif index == 3:
            lines += plan['summary']
        elif index == 4:
            lines += [f'썸네일 {i + 1}: {t["text"]} · {t["image"]}' for i, t in enumerate(plan['thumbnails'])]
            lines += [f'제목 {i + 1}: {t}' for i, t in enumerate(plan['titles'])]
            lines += [f'조합: 썸네일 {plan["pair"]["thumbnail"] + 1} + 제목 {plan["pair"]["title"] + 1}', plan['pair']['reason']]
        else:
            lines += [plan['post_caption']]
        lines += [rating(plan['scores'][index])]
    lines += ['\n확인할 자료:']
    lines += [f'- {f["kind"]}: {f["text"]} · {f["status"]} · {f["url"] or "출처 없음"} · {f["checked_on"] or "기준일 없음"} · {f["conditions"] or "조건 없음"}' for f in plan['facts']]
    lines += plan['checklist']
    weakest = plan['weakest']
    lines += [f'가장 약한 항목: {HEADINGS[weakest]} · 우선 수정: {plan["scores"][weakest]["improvement"]}', plan['goal']]
    return '\n\n'.join(lines)
