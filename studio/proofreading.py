"""Conservative, explainable review. Suggestions never replace the user's words."""
import hashlib
import json
import re

RULES = [
    ('됬', '됐', '되었다의 준말은 됐다입니다.'),
    ('되요', '돼요', '되어요의 준말은 돼요입니다. 문맥을 확인해 주세요.'),
    ('할께', '할게', '약속을 나타내는 어미는 -ㄹ게입니다.'),
    ('먹을께', '먹을게', '약속을 나타내는 어미는 -ㄹ게입니다.'),
    ('몇일', '며칠', '날짜·기간을 묻는 표준 표기는 며칠입니다.'),
    ('왠만', '웬만', '웬만하다의 표기를 확인해 주세요.'),
    ('설겆이', '설거지', '표준 표기는 설거지입니다.'),
    ('어의없', '어이없', '황당하다는 뜻의 표기는 어이없다입니다.'),
]


def dictionary(value):
    result = []
    for line in str(value or '').splitlines()[:100]:
        if '=>' in line:
            wrong, right = (p.strip() for p in line.split('=>', 1))
            if wrong and right and wrong != right and len(wrong) <= 100 and len(right) <= 100:
                result.append((wrong, right, '직접 등록한 제품명·표기입니다. 실제 발음을 확인해 주세요.'))
    return result


def inspect_text(text, corrections=''):
    suggestions, seen = [], set()
    for wrong, right, reason in dictionary(corrections) + RULES:
        for match in re.finditer(re.escape(wrong), text):
            key = (match.start(), match.end(), right)
            if key not in seen:
                suggestions.append({'start': match.start(), 'end': match.end(), 'before': wrong,
                                    'after': right, 'reason': reason})
                seen.add(key)
    reasons = []
    if re.search(r'\d|[영일이삼사오육칠팔구십백천만]+\s*(원|점|그램|킬로|개|퍼센트)', text):
        reasons.append('가격·수량·점수 등 숫자를 원음·자료와 대조해 주세요.')
    if re.search(r'(?<![가-힣])(안|못)\s*[가-힣]|않|아니|없|별로', text):
        reasons.append('부정 표현은 빠진 한 글자로 의미가 바뀔 수 있습니다.')
    if re.search(r'\[[^\]]+\]', text):
        reasons.append('미정인 빈칸을 실제 확인한 내용으로 채워 주세요.')
    if re.search(r'[ㅋㅎ]{2,}', text):
        reasons.append('웃음 표기를 요청한 경우에만 유지해 주세요.')
    if re.search(r'품절\s*대란|판매\s*1위|요즘\s*난리|누구나\s*먹', text):
        reasons.append('유행·순위 주장은 기준일과 1차 출처를 확인해 주세요.')
    return {'suggestions': suggestions, 'reasons': reasons,
            'notice': '규칙 기반 검토입니다. 모든 한국어 오타나 사실 오류를 자동으로 찾지는 못합니다.'}


def caption_token(item):
    value = {key: item.get(key) for key in ['text', 'start', 'end', 'source_text', 'source_key']}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def approved(item):
    return bool(item.get('review_token')) and item['review_token'] == caption_token(item)


def require_review(items):
    pending = [i + 1 for i, c in enumerate(items) if c.get('text', '').strip() and not approved(c)]
    if pending:
        raise ValueError(f'자막 검수가 남아 있습니다. 자막 탭에서 원음을 확인하고 검수 완료를 눌러 주세요. 미검수 {len(pending)}개 (첫 자막: {pending[0]}번).')
    if any(re.search(r'\[[^\]]+\]', c['text']) for c in items):
        raise ValueError('자막에 미정 빈칸이 남아 있습니다. 실제 내용으로 채운 뒤 내보내 주세요.')
