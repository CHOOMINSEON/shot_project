import hashlib
import json
import math
import re

from .settings import MAX_OUTPUT_SECONDS
from . import proofreading, conti


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


MAX_LAYER_TRACKS = 5   # 기본 줄 1개 + 레이어 5줄 = 6줄


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
        visual = assets.get(clip.get('visual_asset_id'))
        if clip.get('visual_asset_id'):
            visual_start = clip.get('visual_start', 0)
            if not visual or visual['status'] != 'ready' or not visual['metadata'].get('has_video', True) or not finite(visual_start) or not 0 <= visual_start < visual['metadata']['duration']:
                raise ValueError('더빙에 연결할 실제 영상과 시작 시간을 확인해 주세요.')
            visual_end=clip.get('visual_end',visual['metadata']['duration'])
            if not finite(visual_end) or not visual_start<visual_end<=visual['metadata']['duration']+.001:
                raise ValueError('선택한 실제 영상 장면의 종료 시간을 확인하세요.')
        if not asset['metadata'].get('has_video', True) and not visual:
            raise ValueError('더빙 구간에는 촬영 영상을 연결해 주세요.')
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
    layers = state.get('layers', [])
    if not isinstance(layers, list) or len(layers) > 500:
        raise ValueError('레이어 구간은 최대 500개까지 지원합니다.')
    seen_layers = set()
    for layer in layers:
        if not isinstance(layer, dict) or not isinstance(layer.get('id'), str) or layer['id'] in seen_layers:
            raise ValueError('레이어 구간 ID가 중복되었거나 올바르지 않습니다.')
        seen_layers.add(layer['id'])
        asset = assets.get(layer.get('asset_id'))
        if not asset or asset['status'] != 'ready':
            raise ValueError('레이어에는 검사가 완료된 원본만 놓을 수 있습니다.')
        track = layer.get('track')
        if not isinstance(track, int) or isinstance(track, bool) or not 1 <= track <= MAX_LAYER_TRACKS:
            raise ValueError('레이어 줄 번호가 올바르지 않습니다.')
        start, end, at = layer.get('start'), layer.get('end'), layer.get('at')
        if not finite(start) or not finite(end) or not finite(at) or start < 0 or end <= start or at < 0 or at > 6 * 3600 \
                or end > asset['metadata']['duration'] + .001:
            raise ValueError('레이어 구간의 시간을 원본 범위 안에서 설정해 주세요.')
        layer['start'] = round(start * fps) / fps
        layer['end'] = min(round(end * fps) / fps, math.floor(asset['metadata']['duration'] * fps) / fps)
        layer['at'] = round(at * fps) / fps
        if layer['end'] <= layer['start']:
            raise ValueError('레이어 구간은 출력 프레임 하나 이상이어야 합니다.')
        volume = layer.get('volume', 1)
        if not finite(volume) or not 0 <= volume <= 2:
            raise ValueError('레이어 소리 크기는 0~2 사이로 설정해 주세요.')
        if (layer.get('frame') or {}).get('mode', 'fit') not in ['fit', 'fill', 'blur']:
            raise ValueError('지원하지 않는 화면 설정입니다.')
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
    if state.get('layers'):
        content.append(state['layers'])
    if output_speed(state) != 1:
        content.append(output_speed(state))   # 배속이 바뀌면 이전 출력은 재사용하지 않는다
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


def voice_words(asset):
    """인식기 단어 시간 → 실제 목소리(VAD) 위치에 맞춘 단어 시간.

    실제 원본(1122 가나 프리미엄)에서 Whisper 단어 시간이 목소리보다 0.4~1초 늦었고, 한 단어가 문장 안
    긴 쉼을 덮을 만큼 길게 찍히기도 했다. 자동 편집은 컷을 목소리(VAD) 기준으로 자르므로 자막도 같은 기준으로
    맞춘다. 문장(쉼 0.7초·문장부호 기준) 단위로 guided.snap_to_voice 로 목소리 시작·끝·문장 안 쉼을 찾고,
    단어를 인식기 안의 상대 위치 그대로 '목소리가 나는 시간'에만 펼친다. VAD가 없으면 원래 시간을 쓴다.
    """
    analysis = asset.get('analysis', {})
    words = [w for w in analysis.get('words', []) if finite(w.get('start')) and finite(w.get('end')) and w['end'] > w['start']]
    from .guided import voiced
    voice = voiced(analysis)   # 버벅이며 다시 말한 앞 시도는 편집에서 빠지므로 자막도 거기 두지 않는다
    if not voice or not words:
        return [dict(w) for w in words]
    from .guided import SWALLOW, lead_before_restart, retold, skip_swallowed, snap_to_voice
    restarts = [(float(x), float(y)) for x, y in analysis.get('restarts') or []]
    groups, bucket = [], []
    for word in words:
        if bucket and (word['start'] - bucket[-1]['end'] > .7 or word['end'] - bucket[0]['start'] > 12):
            groups.append(bucket)
            bucket = []
        bucket.append(word)
        if re.search(r'[.?!。…]$', word['text'].strip()):
            groups.append(bucket)
            bucket = []
    if bucket:
        groups.append(bucket)
    duration = float((asset.get('metadata') or {}).get('duration') or max(w['end'] for w in words))
    result, prev_end = [], 0.
    for i, group in enumerate(groups):
        start, end = float(group[0]['start']), float(group[-1]['end'])
        nxt = float(groups[i + 1][0]['start']) if i + 1 < len(groups) else duration
        swallow = any(float(w['end']) - float(w['start']) > SWALLOW for w in group)
        again = retold(start, end, voice, restarts, [(float(g[0]['start']), float(g[-1]['end'])) for g in groups if g is not group]) \
            if restarts else None
        if again:   # 앞 시도만 받아 적힌 문장: 끝까지 다시 말한 목소리에 자막을 놓는다(편집도 그쪽을 쓴다)
            start, end, swallow = again[0], again[1], True
        s0, s1, gaps = snap_to_voice(start, end, voice, prev_end, max(nxt, end), swallow)
        if gaps:   # 자동 편집이 빼는 '받아 적지 않은 반복' 구간에는 자막 단어를 펼치지 않는다
            s0, gaps = skip_swallowed(s0, s1, gaps, [(float(w['start']), float(w['end'])) for w in group])
        if restarts and not again:
            s0, gaps = lead_before_restart(start, s0, gaps, voice, restarts, prev_end)
            if gaps and s0 < start - .3:
                swallow = True   # 첫마디를 앞에서 찾았으면 인식기 시간 비율 대신 글자 수 비율로 펼친다
        pieces, cursor = [], s0
        for a, b in gaps:
            pieces.append((cursor, a))
            cursor = b
        pieces.append((cursor, s1))
        pieces = [(a, b) for a, b in pieces if b > a]
        total = sum(b - a for a, b in pieces)
        if total <= 0 or end <= start:
            result += [dict(w) for w in group]
            prev_end = end
            continue

        spans = [(float(w['start']), float(w['end'])) for w in group]
        if swallow:
            # 한 단어가 반복·재시작을 삼켜 길게 찍힌 문장(1122 '필링까지' 133~141초)은 인식기 시간 비율이 틀린다.
            # 글자 수 비율로 목소리 구간에 펼친다(사용자 캡처: '필링까지' 다음 '캐러멜칩이'를 말하는 0:14에 자막이 없었다).
            sizes = [max(1, len(re.sub(r'[^가-힣A-Za-z0-9]', '', w['text']))) for w in group]
            edge, spans = 0, []
            for n in sizes:
                spans.append((start + (end - start) * edge / sum(sizes), start + (end - start) * (edge + n) / sum(sizes)))
                edge += n

        def place(t):
            # 인식기 문장 안의 상대 위치(0~1) → 목소리 구간들을 이어 붙인 시간 → 원본 시간
            left = max(0., min(1., (t - start) / (end - start))) * total
            for n, (a, b) in enumerate(pieces):
                if left <= b - a + 1e-9 or n == len(pieces) - 1:
                    return n, a + min(left, b - a)
                left -= b - a
        for word, (w0, w1) in zip(group, spans):
            (n0, a), (n1, b) = place(w0), place(w1)
            if n1 != n0:
                # 쉼을 건너는 단어: 가장 많이 걸친 목소리 구간 하나 안에 둔다.
                best = max(range(n0, n1 + 1), key=lambda n: min(b, pieces[n][1]) - max(a, pieces[n][0]))
                a, b = max(a, pieces[best][0]), min(b, pieces[best][1])
            if b - a < .05:
                b = a + .05
            result.append({**word, 'start': round(a, 3), 'end': round(b, 3),
                           'asr_start': word['start'], 'asr_end': word['end']})
        prev_end = s1
    return result


CAPTION_ENGINE = 3   # 자막 만드는 방식이 바뀌면 올린다. 이전 방식으로 만든 자막은 프로젝트를 열 때 다시 만든다.


def stale_captions(state):
    caps = state.get('captions') or {}
    items = caps.get('items') or []
    # 인식 결과로 만든 자막만 다시 만든다. 직접 입력한 자막(인식 근거 없음)만 있으면 그대로 둔다.
    return caps.get('engine', 0) < CAPTION_ENGINE and any(i.get('source_key') for i in items) \
        and all(i.get('source_key') or i.get('edited') for i in items)


def generate_captions(state, assets, target=14):
    target = max(10, min(30, int(target)))
    result = []
    existing = {item['id']: item for item in state.get('captions', {}).get('items', [])}
    by_source = {}
    for item in existing.values():
        if item.get('source_key'):
            by_source.setdefault(item['source_key'], []).append(item)
    used = set()
    aligned = {}
    # 1) 각 단어를 '목소리 가운데'가 들어 있는 컷 하나에만 놓는다. 몽타주처럼 같은 말을 잘게 나눈 컷이나
    #    쉼을 뺀 컷에서 같은 단어가 여러 번 자막으로 나오지 않는다.
    clips = state.get('clips', [])
    offsets, offset = [], 0.
    for clip in clips:
        offsets.append(offset)
        offset += clip['end'] - clip['start']

    def contiguous(a, b):
        return a['asset_id'] == b['asset_id'] and abs(a['end'] - b['start']) < .02

    # 1) 단어마다 '목소리가 가장 많이 들어 있는 컷' 하나를 고르고, 같은 단어(원본·단어 번호)는 영상 전체에서 한 번만 쓴다.
    #    (1122 프로젝트 실측: 0.27초 몽타주 컷 4개에 '먼저'가 4번, 쉼을 뺀 컷 3개에 '필링까지'가 3번 나왔다.)
    #    컷 안에 0.08초도 안 남은 단어는 잘려 나간 말이라 쓰지 않는다.
    # 같은 원본 소리가 뒤로 감기지 않고 이어지는 컷들(몽타주 조각·쉼을 뺀 컷)을 한 덩어리로 본다. 사용자가 컷을 복제해
    # 같은 소리가 실제로 두 번 나오면 덩어리가 달라 자막도 두 번 나온다.
    runs, run = [], 0
    for i, clip in enumerate(clips):
        if i and (clip['asset_id'] != clips[i - 1]['asset_id'] or clip['start'] < clips[i - 1]['end'] - .05):
            run += 1
        runs.append(run)
    best = {}
    for i, clip in enumerate(clips):
        if clip['asset_id'] not in aligned:
            # 영상 콘티의 편의점·제품 이름으로 인식 오류를 고친다('수유 소금우유는' → 'CU 소금우유는', '호주차' → '호지차')
            aligned[clip['asset_id']] = conti.correct_words(voice_words(assets[clip['asset_id']]), state.get('storyboard', ''))
        for n, word in enumerate(aligned[clip['asset_id']]):
            inside = min(word['end'], clip['end']) - max(word['start'], clip['start'])
            if inside < min(.08, (word['end'] - word['start']) * .5):
                continue
            key = (runs[i], clip['asset_id'], word.get('id', n))
            if key not in best or inside > best[key][0] + 1e-6:
                best[key] = (inside, i, word)
    placed = []
    for inside, i, word in sorted(best.values(), key=lambda v: (v[1], v[2]['start'])):
        clip = clips[i]
        # 소리가 끊김 없이 이어지는 앞뒤 컷(몽타주 조각)까지는 단어가 걸쳐 보여도 된다.
        lo = i
        while lo > 0 and contiguous(clips[lo - 1], clips[lo]):
            lo -= 1
        hi = i
        while hi + 1 < len(clips) and contiguous(clips[hi], clips[hi + 1]):
            hi += 1
        span0, span1 = offsets[lo], offsets[hi] + clips[hi]['end'] - clips[hi]['start']
        start = max(span0, offsets[i] + word['start'] - clip['start'])
        end = min(span1, offsets[i] + word['end'] - clip['start'])
        if placed and placed[-1]['word']['text'].strip() == word['text'].strip() and start - placed[-1]['end'] < .5:
            placed[-1]['end'] = max(placed[-1]['end'], end)   # 인식기가 같은 말을 겹쳐 적은 것(먼저 먼저)은 하나로
            continue
        if end > start:
            placed.append({'word': word, 'clip': clip, 'start': start, 'end': end})
    bucket = []

    def flush():
        if not bucket:
            return
        first, last = bucket[0], bucket[-1]
        words = [p['word'] for p in bucket]
        clip, last_clip = first['clip'], last['clip']
        start, end = first['start'], last['end']
        text = ''.join(w['text'] for w in words).strip()
        ident = f"{clip['id']}:{words[0]['id']}:{words[-1]['id']}"
        source_key = f"{clip['asset_id']}:{words[0]['id']}:{words[-1]['id']}"
        matches = by_source.get(source_key, [])
        previous = existing.get(ident) or (matches[0] if len(matches) == 1 else {})
        if previous:
            used.add(previous['id'])
        review_reasons = []
        if any(w.get('review') for w in words):
            review_reasons.append('인식 신뢰도가 낮은 단어가 있습니다.')
        if any(p['word']['start'] < p['clip']['start'] - .05 or p['word']['end'] > p['clip']['end'] + .05 for p in bucket):
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
                       'source_asset_id': clip['asset_id'], 'source_start': max(clip['start'], words[0]['start']),
                       'source_end': min(last_clip['end'], words[-1]['end']),
                       'review': bool(review_reasons or inspection['suggestions']), 'review_reasons': review_reasons,
                       'confidence': round(min(float(w.get('confidence', 0.)) for w in words), 3),
                       'review_token': previous.get('review_token', ''), 'edited': previous.get('edited', False)})
        bucket.clear()

    for p in placed:
        if bucket:
            prev = bucket[-1]
            jump = p['word']['start'] - prev['word']['end']
            # 쉼만 뺀 바로 다음 컷(같은 원본, 2초 안)은 한 자막으로 이어 준다. 다른 장면으로 넘어가면 끊는다.
            joined = prev['clip'] is p['clip'] or (prev['clip']['asset_id'] == p['clip']['asset_id'] and -.05 <= jump <= 2.)
            if (not joined or len(''.join(x['word']['text'] for x in bucket)) + len(p['word']['text']) > target
                    or p['start'] - prev['end'] > .5):
                flush()
        bucket.append(p)
        if re.search(r'[.!?。]$', p['word']['text'].strip()):
            flush()
    flush()
    for first, second in zip(result, result[1:] + [None]):
        # 너무 짧게 스치는 자막(몽타주 등)은 다음 자막 전까지 최소 0.6초는 보이게 한다.
        limit = second['start'] if second else offset
        if first['end'] - first['start'] < .6:
            first['end'] = round(min(limit, first['start'] + .6), 3)
        if second and first['end'] > second['start']:
            first['end'] = second['start']
    result = [c for c in result if c['end'] > c['start']]
    deduped = []
    for c in result:   # 마지막 안전장치: 바로 앞 자막과 글자가 같고 붙어 있으면 하나로 합친다
        if deduped and c['text'].strip() == deduped[-1]['text'].strip() and c['start'] - deduped[-1]['end'] < .5:
            deduped[-1]['end'] = c['end']
            continue
        deduped.append(c)
    result = deduped
    archive = state.get('captions', {}).get('archived_edits', [])[:]
    archive += [{**item, 'archive_reason': '구간·글자 수가 바뀌어 자동 대응하지 못한 수정 자막'}
                for item in existing.values() if item.get('edited') and item['id'] not in used]
    archive = list({(c['id'], c['text']): c for c in archive}.values())
    return {'signature': signature(state), 'items': result, 'archived_edits': archive, 'engine': CAPTION_ENGINE}



def sync_captions(before,state,assets):
    """Remap edited/manual captions through source time when cuts or order change."""
    result=generate_captions(state,assets)
    source_edits=[]
    offset=0
    olditems=state.get('captions',{}).get('items',[])
    # before contains timing before the mutation; state retains user's latest text edits.
    for clip in before.get('clips',[]):
        length=clip['end']-clip['start']
        for item in olditems:
            if not item.get('edited') and item.get('source_key'):continue
            a=max(offset,item['start']);b=min(offset+length,item['end'])
            if b>a:source_edits.append((clip['asset_id'],clip['start']+a-offset,clip['start']+b-offset,item))
        offset+=length
    mapped=[];used=set();offset=0
    for clip in state.get('clips',[]):
        for asset_id,a,b,item in source_edits:
            if asset_id!=clip['asset_id']:continue
            left=max(a,clip['start']);right=min(b,clip['end'])
            if right<=left:continue
            new={**item,'id':item['id']+':'+clip['id'],'start':round(offset+left-clip['start'],3),
                 'end':round(offset+right-clip['start'],3),'source_asset_id':asset_id,'source_start':left,'source_end':right,
                 'edited':True,'review_token':'','reviewed':False,'review':True,
                 'review_reasons':list(dict.fromkeys(item.get('review_reasons',[])+['컷·순서 변경 후 자막 위치·원음 재검수 필요']))}
            if new['end']>new['start']:mapped.append(new);used.add(item['id'])
        offset+=clip['end']-clip['start']
    # A source-mapped user edit takes precedence over regenerated ASR in its interval.
    remaining=[c for c in result['items'] if not any(m['start']<c['end'] and m['end']>c['start'] for m in mapped)]
    items=sorted(remaining+mapped,key=lambda c:(c['start'],c['end']))
    for first,second in zip(items,items[1:]):
        if first['end']>second['start']:first['end']=second['start']
    result['items']=[c for c in items if c['end']>c['start']]
    result['archived_edits']=[c for c in result['archived_edits'] if c['id'] not in used]
    result['archived_edits'] += [{**c,'archive_reason':'해당 원본 구간이 삭제되어 표시할 위치 없음'} for c in olditems
                                if c.get('edited') and c['id'] not in used and c['id'] not in {a['id'] for a in result['archived_edits']}]
    return result

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


def output_speed(state):
    """최종 출력 배속(1 = 그대로). 타임라인·미리보기는 원래 속도로 두고 최종 MP4·SRT에만 적용한다."""
    try:
        value = float(state.get('speed', 1) or 1)
    except (TypeError, ValueError):
        return 1.
    return value if 1 < value <= 2 else 1.


def scale_captions(items, speed):
    return [{**c, 'start': c['start'] / speed, 'end': c['end'] / speed} for c in items] if speed != 1 else items


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


def layers_in(state, start, end):
    """[start, end) 편집본 구간에 걸치는 레이어를 그 구간 기준 시간으로 바꿔 돌려준다(아래 줄부터)."""
    out = []
    for layer in sorted(state.get('layers', []), key=lambda l: l['track']):
        length = layer['end'] - layer['start']
        a, b = layer['at'], layer['at'] + length
        if b <= start or a >= end:
            continue
        cut_head = max(0., start - a)
        out.append({**layer, 'start': layer['start'] + cut_head, 'at': max(a, start) - start,
                    'end': layer['start'] + min(length, end - a)})
    return out
