"""Bounded local alignment of a user's script with actual timestamped speech."""
import bisect
import copy
import difflib
import re
import unicodedata
from collections import Counter, defaultdict

from pydantic import BaseModel, Field, field_validator
from . import timeline

EXAMPLE = '''아니 제가 CU 다섯 곳이나 돌아서 겨우 3개 구했거든요?
과연 찾아다닐 만큼 맛있을까?
빠르게 먹어볼게요!
[첫 번째 제품명·실제 맛 평가]이고,
[두 번째 제품명·실제 맛 평가]인데,
[세 번째 제품명·실제 맛 평가].
[찾아다닐 만큼 맛있는지 실제 결론과 이유].
나머지는 매일 재고 검색하고 발품까지 팔았는데 아직 못 찾았어요.
여러분은 다른 빵 먹어보셨어요?'''


class Brief(BaseModel):
    script: str = Field(min_length=1, max_length=10000)
    directions: str = Field(default='', max_length=3000)

    @field_validator('script')
    @classmethod
    def check_script(cls, value):
        if not value.strip() or not 1 <= len([s for s in value.splitlines() if s.strip()]) <= 100:
            raise ValueError('대본은 비어 있지 않은 1~100줄로 입력해 주세요.')
        if any(len(s) > 500 for s in value.splitlines()):
            raise ValueError('긴 문장은 줄바꿈으로 나눠 주세요. 한 줄 최대 500자입니다.')
        return value


def normalized(value):
    value = unicodedata.normalize('NFKC', value).lower()
    value = re.sub(r'씨\s*유', 'cu', value)
    for source, target in [('첫', '1'), ('두', '2'), ('세', '3'), ('네', '4'), ('다섯', '5'), ('여섯', '6')]:
        value = re.sub(source + r'\s*(?=번째|곳|개)', target, value)
    return ''.join(c for c in value if c.isalnum())


def critical_equal(query, source):
    # Fuzzy spelling is never permission to reverse counts, prices or negation.
    return (re.findall(r'\d+', query) == re.findall(r'\d+', source)
            and all((token in query) == (token in source) for token in ['못', '않', '없'])
            and ('안' in query) == ('안' in source))


class Transcript:
    def __init__(self, asset):
        self.asset = asset
        self.words = [w for w in asset['analysis'].get('words', []) if normalized(w.get('text', ''))
                      and timeline.finite(w.get('start')) and timeline.finite(w.get('end'))
                      and 0 <= w['start'] < w['end'] <= asset['metadata']['duration'] + .001]
        # Normalize across ASR word boundaries (e.g. '다섯' + '곳', '씨' + '유'),
        # retaining ownership so the selected source timing includes every syllable.
        raw_parts = [''.join(c for c in unicodedata.normalize('NFKC',w['text']).lower() if c.isalnum()) for w in self.words]
        text = ''.join(raw_parts)
        owners = [index for index,part in enumerate(raw_parts) for _ in part]
        rules = [('씨유','cu')] + [(source+r'(?=번째|곳|개)',target) for source,target in
                                [('첫','1'),('두','2'),('세','3'),('네','4'),('다섯','5'),('여섯','6')]]
        for pattern,replacement in rules:
            for match in reversed(list(re.finditer(pattern,text))):
                a,b=match.span()
                text=text[:a]+replacement+text[b:]
                owners[a:b]=[owners[a]]*len(replacement)
        parts=[[] for _ in self.words]
        for char,owner in zip(text,owners):
            parts[owner].append(char)
        self.parts = [''.join(part) for part in parts]
        self.offsets = [0]
        for part in self.parts:
            self.offsets.append(self.offsets[-1] + len(part))
        self.text = ''.join(self.parts)
        self.grams = defaultdict(list)
        for i in range(len(self.text) - 2):
            self.grams[self.text[i:i+3]].append(i)

    def find(self, query, used, check=lambda: None):
        """가장 비슷한 한 곳. 같은 문장을 여러 번 말했다면 점수가 비슷한 후보 중 가장 또렷한 테이크를 고른다."""
        found = self.candidates(query, used, check)
        if not found:
            return None
        top = max(c['score'] for c in found)
        pool = [c for c in found if c['score'] >= top - .04]
        from .guided import take_quality
        for c in pool:
            c['quality'] = take_quality(self.words[c['first']:c['last']])[0]
        best = max(pool, key=lambda c: (round(c['quality'], 2), c['score'], c['confidence']))
        best['takes'] = len({round(c['start'], 1) for c in pool})
        return best

    def candidates(self, query, used, check=lambda: None):
        if not query or not self.words:
            return []
        votes = Counter()
        exact = self.text.find(query)
        while exact >= 0:
            votes[bisect.bisect_right(self.offsets, exact) - 1] += len(query) * 2
            exact = self.text.find(query, exact + 1)
        for q in range(max(0, len(query) - 2)):
            occurrences = self.grams.get(query[q:q+3], [])
            if len(occurrences) > 500:
                continue
            for pos in occurrences:
                index = bisect.bisect_right(self.offsets, max(0, pos - q)) - 1
                for candidate in [index - 1, index, index + 1]:
                    if 0 <= candidate < len(self.words):
                        votes[candidate] += 1
        found = []
        for start, _ in votes.most_common(80):
            check()
            a = self.words[start]['start']
            for end in range(start + 1, min(len(self.words), start + 100) + 1):
                b = self.words[end-1]['end']
                if end < len(self.words) and not self.parts[end]:
                    continue
                if b-a > 60 or (end > start+1 and self.words[end-1]['start']-self.words[end-2]['end'] > 2):
                    break
                text = self.text[self.offsets[start]:self.offsets[end]]
                if len(text) > len(query)*1.5+3:
                    break
                if len(text) < len(query)*.65 or any(x < b and y > a for x,y in used):
                    continue
                score = difflib.SequenceMatcher(None, query, text, autojunk=False).ratio()
                if score < .84 or (len(query) < 8 and score < .98) or not critical_equal(query, text):
                    continue
                confidence = sum(float(w.get('confidence', 0)) for w in self.words[start:end])/(end-start)
                if confidence < .5:
                    continue
                found.append({'score': round(score, 4), 'confidence': round(confidence, 4),
                              'asset_id': self.asset['id'], 'start': a, 'end': b, 'first': start, 'last': end,
                              'source_text': ''.join(w['text'] for w in self.words[start:end]).strip()})
        return found

    def chunk_times(self, match, chunks):
        """일치한 문장 구간 안에서 대본 줄(chunks)마다 시작·종료 시간을 구한다(글자 정렬 기반)."""
        a, b = self.offsets[match['first']], self.offsets[match['last']]
        span = self.text[a:b]
        queries = [normalized(c) for c in chunks]
        whole = ''.join(queries)
        blocks = difflib.SequenceMatcher(None, whole, span, autojunk=False).get_matching_blocks()

        def locate(pos):
            for blk in blocks:
                if blk.a <= pos < blk.a + blk.size:
                    return blk.b + (pos - blk.a)
            before = [blk for blk in blocks if blk.a + blk.size <= pos and blk.size]
            if before:
                last = before[-1]
                return min(len(span), last.b + last.size + (pos - last.a - last.size))
            return 0
        result, cursor = [], 0
        for query in queries:
            if not query:
                result.append(None)
                continue
            first = max(0, min(len(span) - 1, locate(cursor)))
            last = max(first, min(len(span) - 1, locate(cursor + len(query) - 1)))
            cursor += len(query)
            w1 = bisect.bisect_right(self.offsets, a + first) - 1
            w2 = bisect.bisect_right(self.offsets, a + last) - 1
            w1, w2 = max(match['first'], min(w1, match['last'] - 1)), max(match['first'], min(w2, match['last'] - 1))
            result.append((self.words[w1]['start'], self.words[max(w1, w2)]['end'], w1, max(w1, w2)))
        return result


TERMINAL = re.compile(r'[.?!…。]["\')\]]*\s*$')


def group_lines(lines):
    """자막 한 줄씩 끊어 쓴 대본은 문장 단위로 묶어서 찾는다(짧은 조각은 따로 찾으면 엉뚱한 곳에 맞거나 못 찾는다).

    줄이 대부분 짧을 때(중앙값 10자 미만)만 묶고, 마침표·물음표·느낌표로 끝나는 줄에서 끊는다.
    [빈칸]이 들어간 줄과 너무 긴 묶음(80자 초과)은 따로 둔다. 반환: [(줄 번호 목록, 줄 텍스트 목록)]
    """
    lengths = sorted(len(normalized(t)) for _, t in lines)
    chunked = bool(lengths) and lengths[len(lengths) // 2] < 10
    groups, current = [], []

    def flush():
        if current:
            groups.append(([i for i, _ in current], [t for _, t in current]))
            current.clear()
    for i, text in lines:
        if not chunked or re.search(r'\[[^\]]+\]', text):
            flush()
            groups.append(([i], [text]))
            continue
        if current and sum(len(normalized(t)) for _, t in current) + len(normalized(text)) > 80:
            flush()
        current.append((i, text))
        if TERMINAL.search(text):
            flush()
    flush()
    return groups


def script_captions(script_chunks, clips, by_asset, report):
    """문장 단위로 맞춘 구간 안에서 대본 줄마다 자막(SRT)을 만든다. 문구는 사용자가 쓴 대본 그대로, 시간은 실제 음성 기준."""
    offsets, total = {}, 0.
    for clip in clips:
        offsets[clip['id']] = total
        total += clip['end'] - clip['start']
    by_id = {c['id']: c for c in clips}
    done, items = set(), []

    def edited(clip_list, t, end):
        # 원본 시간 t를 편집본 시간으로. 잘려 나간 자리면 가장 가까운 남은 구간으로 맞춘다.
        for c in clip_list:
            if c['start'] - 1e-6 <= t <= c['end'] + 1e-6:
                return offsets[c['id']] + min(max(t, c['start']), c['end']) - c['start']
        if not clip_list:
            return None
        if end:   # 끝 시간: 그 앞에서 가장 가까운 구간의 끝
            before = [c for c in clip_list if c['end'] <= t]
            pick = max(before, key=lambda c: c['end']) if before else clip_list[0]
            return offsets[pick['id']] + (pick['end'] - pick['start'] if before else 0)
        after = [c for c in clip_list if c['start'] >= t]   # 시작 시간: 그 뒤에서 가장 가까운 구간의 시작
        pick = min(after, key=lambda c: c['start']) if after else clip_list[-1]
        return offsets[pick['id']] + (0 if after else pick['end'] - pick['start'])
    for first_clip, match, chunks, numbers in script_chunks:
        key = (match['asset_id'], numbers[0])
        if key in done:
            continue
        done.add(key)
        group_clips = [by_id[cid] for cid, m, cs, ns in script_chunks if ns == numbers and cid in by_id]
        transcript = by_asset[match['asset_id']]
        times = transcript.chunk_times(match, chunks)
        row = next((r for r in report if r.get('lines') and r['lines'][0] == numbers[0] + 1), {})
        for number, text, span in zip(numbers, chunks, times):
            if span is None or not text.strip():
                continue
            start, end = edited(group_clips, span[0], False), edited(group_clips, span[1], True)
            if start is None or end is None or end - start < .05:
                continue
            words = transcript.words[span[2]:span[3] + 1]
            reasons = []
            if match['score'] < .95:
                reasons.append('대본과 실제로 말한 내용이 일부 달라요. 원음으로 확인해 주세요.')
            if min(float(w.get('confidence', 0)) for w in words) < .5:
                reasons.append('인식 신뢰도가 낮은 단어가 있어요.')
            items.append({'id': f'script-{number + 1}', 'start': round(start, 3), 'end': round(end, 3), 'text': text.strip(),
                          'source_text': ''.join(w['text'] for w in words).strip(), 'source_key': f"{match['asset_id']}:script:{number + 1}",
                          'source_asset_id': match['asset_id'], 'source_start': span[0], 'source_end': span[1],
                          'review': bool(reasons), 'review_reasons': reasons,
                          'confidence': round(min(float(w.get('confidence', 0)) for w in words), 3),
                          'review_token': '', 'edited': True, 'from_script': True})
    items.sort(key=lambda c: (c['start'], c['end']))
    for a, b in zip(items, items[1:]):
        if a['end'] > b['start']:
            a['end'] = b['start']
    items = [c for c in items if c['end'] - c['start'] >= .05]
    return {'signature': '', 'items': items, 'archived_edits': []}


def directing(text):
    fast = bool(re.search(r'빠르|빠르게|템포|타이트', text))
    frame = {'mode': 'blur' if '흐린 배경' in text else 'fit', 'x': .5, 'y': .5, 'zoom': 1}
    opening_close = bool(re.search(r'(첫\s*문장|오프닝|1번).*?(클로즈업|확대)', text))
    all_close = ('클로즈업' in text or '화면 채우기' in text) and not opening_close
    supported = ['대본 순서로 원음 연결', '9:16 화면', '긴 무음 줄이기', '대사 경계 여유 유지']
    if fast:
        supported.append('빠른 템포 · 0.35초 이상 대사 공백 축소')
    if opening_close or all_close:
        supported.append('첫 장면 중앙 확대' if opening_close else '중앙 크롭으로 화면 채우기')
    if frame['mode'] == 'blur':
        supported.append('흐린 배경')
    unsupported = []
    for phrase in ['단면', '시식 컷', '얼굴 추적', '음악', '효과음', '전환 효과', '줌인', '자막', '더빙']:
        if phrase in text:
            unsupported.append(f'{phrase}: 자동 적용 전 추가 확인 필요')
    return {'minimum': .35 if fast else .6, 'before': .08 if fast else .12,
            'after': .12 if fast else .2, 'frame': frame, 'opening_close': opening_close,
            'all_close': all_close, 'supported': supported, 'unapplied': unsupported}


def assemble(brief, state, assets, voice_mode='auto', check=lambda: None, scenes=None):
    videos = [a for a in assets.values() if a['status']=='ready' and a['metadata'].get('has_video', True)]
    dubbing = [a for a in assets.values() if a['status']=='ready' and not a['metadata'].get('has_video', True)]
    selected = dubbing if voice_mode=='dubbing' else videos if voice_mode=='original' else dubbing+videos
    transcripts = [Transcript(asset) for asset in selected if asset['metadata'].get('has_audio')]
    used, report, clips = defaultdict(list), [], []
    video_transcripts=[Transcript(a) for a in videos if a['metadata'].get('has_audio')]
    previous_intent=None
    direction = directing(brief.directions)
    by_asset = {t.asset['id']: t for t in transcripts}
    script_chunks = []
    groups = group_lines(list(enumerate(s for s in brief.script.splitlines() if s.strip())))
    for numbers, chunks in groups:
        i, line = numbers[0], ' '.join(c.strip() for c in chunks)
        check()
        item = {'line': i+1, 'script': line, 'status': 'missing', 'reason': '정확한 일치 없음 · 장면 후보도 확인해 주세요.'}
        if len(numbers) > 1:
            item['lines'] = [n + 1 for n in numbers]
        if scenes is not None and normalized(line):
            retrieval=scenes.query(line,previous_intent,check)
            item.update(retrieval)
            # Do not replace script line numbers/status with retrieval status.
            item['status']='missing';item['scene_status']=retrieval['status']
            previous_intent=retrieval['intent']
        if re.search(r'\[[^\]]+\]', line):
            item.update(status='placeholder', reason='제품명·맛 평가·결론을 실제 내용으로 채워 주세요.')
        else:
            query = normalized(line)
            matches = [m for transcript in transcripts if (m := transcript.find(query, used[transcript.asset['id']], check))]
            matches.sort(key=lambda m: (not assets[m['asset_id']]['metadata'].get('has_video',True),m['score'],m['confidence']), reverse=True)
            if matches:
                match = matches[0]
                used[match['asset_id']].append([match['start'], match['end']])
                item.update(match, status='matched',match_type='대사 일치',filename=assets[match['asset_id']]['name'], reason='인식 대사와 대본을 대조해 주세요.' if match['score'] < .98 or match['confidence'] < .85 else '')
                source = assets[match['asset_id']]
                use_dubbing = not source['metadata'].get('has_video',True)
                if len(numbers) > 1 or match.get('takes', 1) > 1:
                    item['takes'] = match.get('takes', 1)
                    if match.get('takes', 1) > 1:
                        item['reason'] = (item['reason'] + ' ' if item['reason'] else '') + f'같은 문장을 {match["takes"]}번 말해 가장 또렷한 테이크를 골랐어요.'
                item['voice'] = 'dubbing' if use_dubbing else 'original'
                a = max(0, match['start'] - direction['before'])
                b = min(source['metadata']['duration'], match['end'] + direction['after'])
                frame = dict(direction['frame'])
                if direction['all_close'] or direction['opening_close'] and i == 0:
                    frame.update(mode='fill', zoom=1.12)
                cuts = timeline.cut_candidates(source['analysis'].get('speech', []), source['metadata']['duration'],
                                               direction['minimum'], direction['before'], direction['after']) if source['analysis'].get('speech') else []
                protections = [(p['start'],p['end']) for p in state.get('protections', []) if p['asset_id']==source['id']]
                if scenes is not None and not use_dubbing:
                    from .scene_index import protected
                    protections+=protected(source['id'])
                effective = [part for c in cuts for part in timeline.subtract([c['start'],c['end']], protections)]
                for index,(start,end) in enumerate(timeline.subtract([a,b],effective)):
                    if end-start >= 1/state.get('fps',30):
                        clip = {'id': f'script-{i+1}-{source["id"]}-{index}', 'asset_id': source['id'], 'start': start, 'end': end,
                                'label': f'{i+1}. {line[:45]}', 'frame': frame, 'script_line': i+1}
                        if use_dubbing and videos:
                            corresponding=[m for t in video_transcripts if (m:=t.find(query,[],check))]
                            corresponding.sort(key=lambda m:(m['score'],m['confidence']),reverse=True)
                            if corresponding:
                                visual_match=corresponding[0];visual=assets[visual_match['asset_id']]
                                visual_start=max(0,visual_match['start']+start-match['start'])
                                visual_start=min(visual_start,visual['metadata']['duration']-1/state.get('fps',30))
                                visual_end=min(visual['metadata']['duration'],visual_match['end']+direction['after'])
                                clip.update(visual_asset_id=visual['id'],visual_start=visual_start,visual_end=max(visual_start+1/state.get('fps',30),visual_end))
                                item.update(visual_asset_id=visual['id'],visual_name=visual['name'],visual_reason='촬영 원본의 같은 실제 대사 장면 연결')
                            else:
                                # Keep real dubbing as a pending voice; never fabricate an upload-order shot.
                                item.update(status='needs_scene',reason='더빙 대사 일치 · 연결할 실제 영상 후보를 선택해 주세요.',pending_voice={'asset_id':source['id'],'start':a,'end':b})
                                continue
                        clips.append(clip)
                        if len(numbers) > 1:
                            script_chunks.append((clip['id'], match, chunks, numbers))
        report.append(item)
    # Avoid showing the same source frames twice when adjacent matched sentences meet.
    for previous,current in zip(clips,clips[1:]):
        if previous['asset_id']==current['asset_id'] and previous['start'] < current['start'] < previous['end']:
            boundary=(previous['end']+current['start'])/2
            previous['end']=boundary;current['start']=boundary
    value = copy.deepcopy(state)
    captions = script_captions(script_chunks, clips, by_asset, report) if script_chunks else None
    value['script_brief'] = brief.model_dump()
    voices={r.get('voice') for r in report if r['status']=='matched'}
    value['script_edit'] = {'lines': report, 'directing': direction, 'voice': 'mixed' if len(voices)>1 else next(iter(voices),'original'),
                            'complete': all(r['status'] in ['matched','selected'] for r in report)}
    value['clips'] = clips
    value['cut_removals'] = []
    if clips:
        timeline.validate_state(value, assets)
        timeline.export_groups(value,'full')
        if captions is not None:
            captions['signature'] = timeline.signature(value)
            value['captions'] = captions
        elif state.get('captions',{}).get('items'):
            # Preserve previous text and archive unmatched manual edits through the existing synchronizer.
            value['captions'] = timeline.sync_captions(state,value,assets)
    return value
