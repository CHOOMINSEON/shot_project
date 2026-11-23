"""영상 콘티(대본) 활용: 제품·편의점 이름으로 인식 오류 고치기, 실제로 찍지 않은 나레이션 줄 찾기, [실제 반응] 단서.

사용자 피드백(2026-11-23): "콘티에도 적혀 있을텐데 대사 참고 안해?" 1122 가나 프리미엄 원본 인식 결과에
'CU'가 '수유', '호지차'가 '호주차', '크림브륄레'가 '빌렐레'·'크림브렐레'로 적혀 자막과 제품 맞추기가 틀렸다.
콘티 첫 세 줄(구하려고 일주일·편의점마다 맛이 달라서·4,800원)은 캡컷에서 따로 녹음한 나레이션이라 원본에 없다.
"""
import re

LETTER = {'A': '에이', 'B': '비', 'C': '씨', 'D': '디', 'E': '이', 'F': '에프', 'G': '지', 'H': '에이치', 'I': '아이', 'J': '제이',
          'K': '케이', 'L': '엘', 'M': '엠', 'N': '엔', 'O': '오', 'P': '피', 'Q': '큐', 'R': '알', 'S': '에스', 'T': '티', 'U': '유',
          'V': '브이', 'W': '더블유', 'X': '엑스', 'Y': '와이', 'Z': '지'}
DIGIT = '영일이삼사오육칠팔구'
BRANDS = ('세븐일레븐', '이마트24', '이마트', 'GS25', 'GS', 'CU', '미니스톱', '편의점')
JOSA = ('부터는', '이라서', '인데요', '인데', '에는', '이랑', '처럼', '보다', '까지', '부터', '이라', '이에요', '예요', '은', '는', '이', '가',
        '도', '의', '에', '를', '을', '랑', '와', '과')
SENSE = {'향', '꿀', '배', '짠', '단', '쓴', '칩'}   # 대괄호 단서 중 한 글자라도 남길 맛·향 낱말
CHO = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ'
JUNG = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ'
JONG = ' ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'


def _number(text):
    def sino(n):
        if n == 0:
            return '영'
        out = ''
        for value, unit in ((1000, '천'), (100, '백'), (10, '십')):
            d, n = divmod(n, value)
            if d:
                out += ('' if d == 1 else DIGIT[d]) + unit
        return out + (DIGIT[n] if n else '')
    return re.sub(r'\d+', lambda m: sino(int(m[0])) if len(m[0]) <= 4 else ''.join(DIGIT[int(c)] for c in m[0]), text)


def reading(term):
    """'CU' → '씨유', 'GS25' → '지에스이십오', '허니&페어' → '허니앤페어'. 인식기는 한글 발음대로 적는다."""
    text = _number(term.replace('&', '앤'))
    return re.sub(r'[A-Za-z]', lambda m: LETTER[m[0].upper()], text).replace(' ', '')


def jamo(text):
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out += [CHO[code // 588], JUNG[code % 588 // 28]] + ([JONG[code % 28]] if code % 28 else [])
        else:
            out.append(ch)
    return out


def similar(a, b):
    a, b = jamo(a), jamo(b)
    if not a or not b:
        return 0.
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b))


def _core(word):
    """' 빌렐레인데,' → ('', '빌렐레', '인데,')"""
    m = re.match(r'^(\s*)(.*?)([.,!?…~]*)$', word, re.S)
    lead, body, punct = m[1], m[2], m[3]
    for j in sorted(JOSA, key=len, reverse=True):
        if body.endswith(j) and len(body) - len(j) >= 2:
            return lead, body[:-len(j)], j + punct
    return lead, body, punct


def lines(text):
    """콘티 줄: [{'text': 대괄호 뺀 문장, 'hints': [대괄호 안 설명]}]. 머리말(#)·목록 기호는 뗀다."""
    out = []
    for raw in re.split(r'\n+', text or ''):
        raw = re.sub(r'^\s*(#+|[-*•]|\d+[.)])\s*', '', raw).strip()
        if not raw or not re.search(r'[가-힣]', raw):
            continue
        hints = re.findall(r'\[([^\]]+)\]', raw)
        out.append({'text': re.sub(r'\s*\[[^\]]*\]\s*', ' ', raw).strip(), 'hints': hints, 'raw': raw})
    return out


def names(text):
    """콘티에서 편의점·제품 이름. 편의점 이름 바로 뒤 단어를 제품 이름으로 본다('CU 소금우유도' → 소금우유)."""
    brands, products, pairs = [], [], []
    for line in lines(text):
        tokens = line['text'].split()
        for i, tok in enumerate(tokens):
            clean = re.sub(r'[^\w&]', '', tok)
            brand = next((b for b in BRANDS if clean == b or (clean.startswith(b) and b != '편의점' and len(clean) > len(b) and not re.match(r'\d', clean[len(b):]))), None)
            if not brand or brand == '편의점':
                continue
            if clean == brand:
                brands.append(brand)
                if i + 1 < len(tokens):
                    product = _core(re.sub(r'[^\w&\s]', '', tokens[i + 1]))[1]
                    if len(product) >= 2 and product not in BRANDS and not re.search(r'(편의점|거|것)$', product):
                        products.append(product)
                        pairs.append((brand, product))
    return {'brands': list(dict.fromkeys(brands)), 'products': list(dict.fromkeys(products)), 'pairs': list(dict.fromkeys(pairs))}


def vocabulary(text):
    found = names(text)
    return found['brands'] + found['products']


def correct_words(words, text):
    """인식 단어를 콘티 이름으로 고친다(원래 글자는 asr_text에 남긴다). 콘티가 없으면 그대로.

    - 발음이 거의 같은 단어: '호주차' → '호지차', '크림브렐레' → '크림브륄레'
    - 긴 이름 뒷부분만 들린 단어: '빌렐레인데' → '크림브륄레인데'
    - 제품 이름 바로 앞 짧은 단어가 콘티에서 그 제품 앞 편의점과 발음이 비슷: '수유 소금우유는' → 'CU 소금우유는'
    """
    found = names(text)
    terms = found['products'] + [b for b in found['brands'] if len(reading(b)) >= 3]
    if not terms:
        return [dict(w) for w in words]
    before = {p: b for b, p in found['pairs']}
    out = [dict(w) for w in words]
    cores = [_core(w.get('text', '')) for w in out]
    for i, (lead, core, tail) in enumerate(cores):
        if len(core) < 2 or not re.fullmatch(r'[가-힣]+', core):
            continue
        best = None
        for term in terms:
            say = reading(term)
            if core == term or core == say:
                best = None
                break
            score = similar(core, say) if abs(len(core) - len(say)) <= 1 else 0.
            if len(core) >= 3 and len(say) >= len(core) + 1:
                score = max(score, similar(core, say[-len(core):]) - .05)   # 긴 이름 뒷부분만 들림
            if score >= .7 and (best is None or score > best[0]):
                best = (score, term)
        if best:
            out[i]['asr_text'] = out[i].get('asr_text', out[i]['text'])
            out[i]['text'] = lead + best[1] + tail
            cores[i] = (lead, best[1], tail)
    after = {b: p for b, p in found['pairs']}
    for i in range(1, len(out)):
        # 편의점 이름 바로 뒤 단어는 콘티에서 그 편의점 제품일 가능성이 커서 기준을 낮춘다('세븐일레븐의 빌렐레인데' → 크림브륄레)
        lead, core, tail = cores[i]
        product = after.get(cores[i - 1][1])
        if not product or core == product or len(core) < 2 or not re.fullmatch(r'[가-힣]+', core):
            continue
        say = reading(product)
        score = similar(core, say)
        if len(core) >= 3 and len(say) > len(core):
            score = max(score, similar(core, say[-len(core):]))
        if score >= .55:
            out[i]['asr_text'] = out[i].get('asr_text', out[i]['text'])
            out[i]['text'] = lead + product + tail
            cores[i] = (lead, product, tail)
    for i in range(len(out) - 1):
        lead, core, tail = cores[i]
        nxt = cores[i + 1][1]
        product = next((p for p in before if nxt == p or nxt.startswith(p)), None)
        brand = before.get(product)
        if not brand or core == brand or not re.fullmatch(r'[가-힣]{1,3}', core or ''):
            continue
        if similar(core, reading(brand)) >= .45:
            out[i]['asr_text'] = out[i].get('asr_text', out[i]['text'])
            out[i]['text'] = lead + brand + tail
    return out


def narration_lines(text, words, rate=13.):
    """콘티 앞부분 중 원본 말에 없는 줄 = 따로 녹음한 나레이션. (줄 목록, 예상 초)

    한 줄의 글자 3글자 묶음 중 원본 말에 나오는 비율이 25% 미만이면 원본에 없는 줄로 본다(2글자 묶음은 '한데'·'니다'처럼
    흔한 말끝이 겹쳐 맞지 않았다). 첫 줄부터 이어지는 줄만, [실제 반응] 줄이 나오면 멈춘다.
    읽는 속도는 초당 약 13글자: 1122 콘티 첫 세 줄(130글자)이 사용자 직접 편집본 1123 첫 약 10초 나레이션이다.
    """
    spoken = re.sub(r'\s+', '', ''.join(w.get('text', '') for w in words))
    have = {spoken[i:i + 3] for i in range(len(spoken) - 2)}
    out = []
    for line in lines(text):
        if line['hints']:
            break
        body = re.sub(r'[^가-힣A-Za-z0-9]', '', line['text'])
        grams = [body[i:i + 3] for i in range(len(body) - 2)]
        if not grams or sum(g in have for g in grams) / len(grams) >= .25:
            break
        out.append(line['text'])
    chars = sum(len(re.sub(r'[^가-힣A-Za-z0-9]', '', t)) for t in out)
    return out, round(chars / rate, 1)


def hints(text):
    """제품 이름 → [실제 반응] 대괄호 안 단서 낱말(2글자 이상, 제품·편의점 이름 뺌). 재구매 줄은 '__재구매__'.

    'CU 소금우유도 … 크림브륄레랑 비교해보니까 [짠맛이 …]'처럼 한 줄에 제품이 둘이면 앞에 나온 제품 줄로 본다.
    """
    found = names(text)
    stop = {'실제', '반응', '대한', '사이로', '얼마나', '느껴지는지', '느껴지는', '정도와', '정도', '차이', '뭐가', '먼저', '느껴졌는지',
            '느껴지', '이유', '또는', '제품명과', '제품명', '않을', '맛과', '맛의', '두', '중'}
    stop |= set(found['products']) | {re.sub(r'\d', '', b) for b in found['brands']} | set(found['brands'])
    out = {}
    for line in lines(text):
        if not line['hints']:
            continue
        at = [(line['text'].find(p), p) for p in found['products'] if p in line['text']]
        product = min(at)[1] if at else ('__재구매__' if re.search(r'다시\s*산|재구매', line['raw']) else None)
        if not product:
            continue
        words = []
        for w in re.findall(r'[가-힣]+', ' '.join(line['hints'])):
            j = next((j for j in sorted(JOSA, key=len, reverse=True) if w.endswith(j) and len(w) > len(j)), '')
            w = w[:len(w) - len(j)] if j else w
            words += [w] + ([w[:-1]] if len(w) == 2 and w.endswith('맛') else [])   # 꿀맛 → 꿀('꿀이랑 배맛이')
        out[product] = list(dict.fromkeys(w for w in words if (len(w) >= 2 or w in SENSE) and w not in stop))
    return out
