import hashlib
import json
import math
import re

from .settings import MAX_OUTPUT_SECONDS
from . import proofreading


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate_state(state, assets):
    if not isinstance(state, dict):
        raise ValueError('편집 정보 형식이 올바르지 않습니다.')
    clips = state.get('clips', [])
    fps = state.get('fps', 30)
    if fps not in [30, 60]:
        raise ValueError('출력 프레임레이트는 30 또는 60fps입니다.')
    if not isinstance(clips, list) or len(clips) > 3000:
        raise ValueError('유지 구간은 최대 3,000개까지 지원합니다.')
    seen = set()
    for clip in clips:
        if not isinstance(clip, dict) or not isinstance(clip.get('id'), str) or clip['id'] in seen:
            raise ValueError('구간 ID가 중복되었거나 올바르지 않습니다.')
        seen.add(clip['id'])
        asset = assets.get(clip.get('asset_id'))
        if not asset or asset['status'] != 'ready':
            raise ValueError('검사가 완료된 원본만 편집할 수 있습니다.')
        start, end = clip.get('start'), clip.get('end')
        if not finite(start) or not finite(end) or start < 0 or end <= start or end > asset['metadata']['duration'] + .001:
            raise ValueError('구간 시작·종료 시간을 원본 범위 안에서 설정해 주세요.')
        # Normalize once, then preview, SRT and render all consume this same frame-aligned timeline.
        clip['start'] = round(start * fps) / fps
        clip['end'] = min(round(end * fps) / fps, math.floor(asset['metadata']['duration'] * fps) / fps)
        if clip['end'] <= clip['start']:
            raise ValueError('유지 구간은 출력 프레임 하나 이상이어야 합니다.')
        frame = clip.get('frame', {})
        if frame.get('mode', 'fit') not in ['fit', 'fill', 'blur']:
            raise ValueError('지원하지 않는 화면 설정입니다.')
        for key, low, high, default in [('x', 0, 1, .5), ('y', 0, 1, .5), ('zoom', 1, 3, 1)]:
            value = frame.get(key, default)
            if not finite(value) or not low <= value <= high:
                raise ValueError('크롭 위치·확대율을 허용 범위 안에서 설정해 주세요.')
    for protection in state.get('protections', []):
        asset = assets.get(protection.get('asset_id'))
        start, end = protection.get('start'), protection.get('end')
        if not asset or asset['status'] != 'ready' or not finite(start) or not finite(end) or not 0 <= start < end <= asset['metadata']['duration']:
            raise ValueError('보존 구간의 시간을 원본 범위 안에서 설정해 주세요.')
    if state.get('fps', 30) not in [30, 60]:
        raise ValueError('출력 프레임레이트는 30 또는 60fps입니다.')
    if state.get('quality', 'standard') not in ['standard', 'high']:
        raise ValueError('화질 옵션이 올바르지 않습니다.')
    return state


def duration(clips):
    return sum(c['end'] - c['start'] for c in clips)


def signature(state):
    content = [{'id': c.get('id'), 'asset_id': c.get('asset_id'),
                'start': round(float(c['start']), 9), 'end': round(float(c['end']), 9)}
               for c in state.get('clips', [])]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def render_signature(state):
    content = [state.get('clips', []), state.get('fps', 30), state.get('quality', 'standard')]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + .001:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return merged


def subtract(interval, cuts):
    parts = [list(interval)]
    for start, end in merge_intervals(cuts):
        remaining = []
        for a, b in parts:
            if end <= a or start >= b:
                remaining.append([a, b])
            else:
                if a < start:
                    remaining.append([a, start])
                if end < b:
                    remaining.append([end, b])
        parts = remaining
    return parts


def cut_candidates(speech, length, minimum=.6, before=.12, after=.2):
    cursor, result = 0., []
    for start, end in merge_intervals(speech) + [[length, length]]:
        if start - cursor >= minimum:
            a, b = max(0, cursor + (after if cursor else 0)), max(0, start - (before if start < length else 0))
            if b > a:
                result.append({'start': a, 'end': b})
        cursor = max(cursor, end)
    return result


def apply_cuts(state, asset_id, candidates):
    protections = [(p['start'], p['end']) for p in state.get('protections', []) if p['asset_id'] == asset_id]
    cuts = [piece for c in candidates for piece in subtract([c['start'], c['end']], protections)]
    result = []
    for clip in state['clips']:
        if clip['asset_id'] != asset_id:
            result.append(clip)
            continue
        for start, end in cuts:
            a, b = max(start, clip['start']), min(end, clip['end'])
            if b > a:
                state.setdefault('cut_removals', []).append({'asset_id': asset_id, 'start': a, 'end': b,
                                                            'label': clip.get('label'), 'frame': clip.get('frame', {})})
        parts = subtract([clip['start'], clip['end']], cuts)
        if parts == [[clip['start'], clip['end']]]:
            result.append(clip)
            continue
        for index, (start, end) in enumerate(parts):
            if end - start >= .02:
                result.append({**clip, 'id': f"{clip['id']}.{index}", 'start': start, 'end': end})
    state['clips'] = result
    return state


def restore_cuts(state, asset_id, candidates):
    for candidate in candidates:
        recorded = [r for r in state.get('cut_removals', []) if r['asset_id'] == asset_id]
        existing = [(c['start'], c['end']) for c in state['clips'] if c['asset_id'] == asset_id]
        ranges = merge_intervals([[max(r['start'], candidate['start']), min(r['end'], candidate['end'])] for r in recorded])
        for start, end in [p for interval in ranges for p in subtract(interval, existing)]:
            preceding = [(i, c) for i, c in enumerate(state['clips']) if c['asset_id'] == asset_id and c['end'] <= start + .001]
            index, neighbor = max(preceding, key=lambda pair: pair[1]['end']) if preceding else (-1, {})
            ident = hashlib.sha256(f'{asset_id}:{start}:{end}:{len(state["clips"])}'.encode()).hexdigest()
            restored = {'id': ident, 'asset_id': asset_id, 'start': start, 'end': end,
                        'label': neighbor.get('label', '복원 구간'), 'frame': neighbor.get('frame', {'mode': 'fit'})}
            state['clips'].insert(index + 1 if preceding else 0, restored)
        remaining = []
        for removal in state.get('cut_removals', []):
            if removal['asset_id'] != asset_id:
                remaining.append(removal)
            else:
                remaining += [{**removal, 'start': a, 'end': b}
                              for a, b in subtract([removal['start'], removal['end']], [[candidate['start'], candidate['end']]])]
        state['cut_removals'] = remaining
    return state


def generate_captions(state, assets, target=14):
    target = max(10, min(30, int(target)))
    offset, result = 0., []
    existing = {item['id']: item for item in state.get('captions', {}).get('items', [])}
    by_source = {}
    for item in existing.values():
        if item.get('source_key'):
            by_source.setdefault(item['source_key'], []).append(item)
    used = set()
    for clip in state.get('clips', []):
        words = assets[clip['asset_id']]['analysis'].get('words', [])
        bucket = []
        def flush():
            if not bucket:
                return
            first, last = bucket[0], bucket[-1]
            start = offset + max(0, first['start'] - clip['start'])
            end = offset + min(clip['end'] - clip['start'], last['end'] - clip['start'])
            text = ''.join(w['text'] for w in bucket).strip()
            ident = f"{clip['id']}:{first['id']}:{last['id']}"
            source_key = f"{clip['asset_id']}:{first['id']}:{last['id']}"
            matches = by_source.get(source_key, [])
            previous = existing.get(ident) or (matches[0] if len(matches) == 1 else {})
            if previous:
                used.add(previous['id'])
            review_reasons = []
            if any(w.get('review') for w in bucket):
                review_reasons.append('인식 신뢰도가 낮은 단어가 있습니다.')
            if first['start'] < clip['start'] or last['end'] > clip['end']:
                review_reasons.append('컷 경계에서 단어가 잘릴 수 있습니다.')
            if end - start < .35 or end - start > 7:
                review_reasons.append('자막 표시 길이를 확인해 주세요.')
            current_text = previous.get('text', text)
            inspection = proofreading.inspect_text(current_text, state.get('corrections', ''))
            review_reasons += inspection['reasons']
            if state.get('vocabulary'):
                review_reasons.append('제품명·브랜드를 등록한 표기와 대조해 주세요.')
            # Preserve text edits, while always recomputing timing after timeline changes.
            result.append({'id': ident, 'start': round(start, 3), 'end': round(end, 3),
                           'text': current_text, 'source_text': text, 'source_key': source_key,
                           'source_asset_id': clip['asset_id'], 'source_start': max(clip['start'], first['start']),
                           'source_end': min(clip['end'], last['end']),
                           'review': bool(review_reasons or inspection['suggestions']), 'review_reasons': review_reasons,
                           'confidence': round(min(float(w.get('confidence', 0.)) for w in bucket), 3),
                           'review_token': previous.get('review_token', ''), 'edited': previous.get('edited', False)})
            bucket.clear()
        for word in words:
            if word['end'] <= clip['start'] or word['start'] >= clip['end']:
                continue
            if bucket and (len(''.join(w['text'] for w in bucket)) + len(word['text']) > target
                           or word['start'] - bucket[-1]['end'] > .5):
                flush()
            bucket.append(word)
            if re.search(r'[.!?。]$', word['text'].strip()):
                flush()
        flush()
        offset += clip['end'] - clip['start']
    archive = state.get('captions', {}).get('archived_edits', [])[:]
    archive += [{**item, 'archive_reason': '구간·글자 수가 바뀌어 자동 대응하지 못한 수정 자막'}
                for item in existing.values() if item.get('edited') and item['id'] not in used]
    archive = list({(c['id'], c['text']): c for c in archive}.values())
    return {'signature': signature(state), 'items': result, 'archived_edits': archive}


def validate_captions(items, length):
    previous_end = 0
    for item in sorted(items, key=lambda c: c['start']):
        a, b = item.get('start'), item.get('end')
        if not finite(a) or not finite(b) or not 0 <= a < b <= length + .001:
            raise ValueError('자막 시간이 음수·역전·영상 길이 초과인지 확인해 주세요.')
        if round(b * 1000) <= round(a * 1000):
            raise ValueError('자막 길이는 SRT의 1밀리초 단위로 표시할 수 있어야 합니다.')
        if a < previous_end - .001:
            raise ValueError('자막 시간이 겹칩니다. 시작·종료 시간을 조정해 주세요.')
        if not isinstance(item.get('text'), str) or len(item['text']) > 2000:
            raise ValueError('자막 문구가 올바르지 않습니다.')
        previous_end = b


def timecode(seconds):
    ms = max(0, round(seconds * 1000))
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}'


def srt(items, length):
    items = sorted([c for c in items if c['text'].strip()], key=lambda c: c['start'])
    validate_captions(items, length)
    return ''.join(f"{i}\n{timecode(c['start'])} --> {timecode(c['end'])}\n{c['text'].strip()}\n\n" for i, c in enumerate(items, 1))


def local_captions(items, start, end):
    return [{**c, 'start': max(c['start'], start) - start, 'end': min(c['end'], end) - start}
            for c in items if c['start'] < end and c['end'] > start]


def export_groups(state, mode):
    clips = state.get('clips', [])
    if not clips:
        raise ValueError('내보낼 유지 구간이 없습니다.')
    if mode == 'full':
        groups = [('전체 컷편집본', clips)]
    elif mode == 'cuts':
        groups = [(c.get('label') or f'컷 {i}', [c]) for i, c in enumerate(clips, 1)]
    elif mode == 'products':
        groups = []
        for clip in clips:
            label = clip.get('label') or '미분류'
            if groups and groups[-1][0] == label:
                groups[-1][1].append(clip)
            else:
                groups.append((label, [clip]))
    else:
        raise ValueError('내보내기 종류가 올바르지 않습니다.')
    if any(duration(group) > MAX_OUTPUT_SECONDS + 1e-6 for _, group in groups):
        raise ValueError('출력 영상당 최대 30분입니다. 유지 구간을 줄이거나 제품별·컷별로 나눠 출력해 주세요. 자동으로 잘라내지 않습니다.')
    return groups


def product_candidates(words, names, length):
    candidates = []
    phrases = ['첫 번째', '첫번째', '다음은', '이번에는', '두 번째', '세 번째']
    for i, word in enumerate(words):
        text = ''.join(w['text'] for w in words[i:i + 8])
        name = next((name for name in names if name and name in text), None)
        transition = any(phrase in text for phrase in phrases)
        if (name or transition) and (not candidates or word['start'] - candidates[-1]['start'] > 12):
            candidates.append({'name': name or '제품명 확인 필요', 'start': word['start'], 'review': True})
    if not candidates or candidates[0]['start'] > 1:
        candidates.insert(0, {'name': '오프닝 / 구간 확인', 'start': 0, 'review': True})
    for i, c in enumerate(candidates):
        c['end'] = candidates[i + 1]['start'] if i + 1 < len(candidates) else length
        c['text'] = ''.join(w['text'] for w in words if c['start'] <= w['start'] < c['end']).strip()
    return candidates
