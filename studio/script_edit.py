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
        if not query or not self.words:
            return None
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
        best = None
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
                choice = {'score': round(score, 4), 'confidence': round(confidence, 4),
                          'asset_id': self.asset['id'], 'start': a, 'end': b,
                          'source_text': ''.join(w['text'] for w in self.words[start:end]).strip()}
                if best is None or (score, confidence) > (best['score'], best['confidence']):
                    best = choice
        return best


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
    for i, line in enumerate(s for s in brief.script.splitlines() if s.strip()):
        check()
        item = {'line': i+1, 'script': line, 'status': 'missing', 'reason': '정확한 일치 없음 · 장면 후보도 확인해 주세요.'}
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
        report.append(item)
    # Avoid showing the same source frames twice when adjacent matched sentences meet.
    for previous,current in zip(clips,clips[1:]):
        if previous['asset_id']==current['asset_id'] and previous['start'] < current['start'] < previous['end']:
            boundary=(previous['end']+current['start'])/2
            previous['end']=boundary;current['start']=boundary
    value = copy.deepcopy(state)
    value['script_brief'] = brief.model_dump()
    voices={r.get('voice') for r in report if r['status']=='matched'}
    value['script_edit'] = {'lines': report, 'directing': direction, 'voice': 'mixed' if len(voices)>1 else next(iter(voices),'original'),
                            'complete': all(r['status'] in ['matched','selected'] for r in report)}
    value['clips'] = clips
    value['cut_removals'] = []
    if clips:
        timeline.validate_state(value, assets)
        timeline.export_groups(value,'full')
        if state.get('captions',{}).get('items'):
            # Preserve previous text and archive unmatched manual edits through the existing synchronizer.
            value['captions'] = timeline.sync_captions(state,value,assets)
    return value
