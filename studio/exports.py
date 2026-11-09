"""컷 구성을 다른 편집기에서 이어 편집하기 위한 보조 파일(EDL · FCPXML · 컷 목록).

정직한 지원 범위
- 캡컷 PC가 EDL/FCPXML을 직접 가져오는지는 확인하지 못했습니다(미검증). 이 파일들은 DaVinci Resolve·
  Premiere·Final Cut 계열에서 컷 경계를 복원하는 용도로 만들었습니다.
- 캡컷으로 옮기는 확실한 방법은 '컷별 MP4 + 가져오기 순서 목록'입니다(제품/컷별 출력 모드).
  이 목록(import-order.txt)이 순서·길이·원본 구간을 알려 줍니다.
"""
from xml.sax.saxutils import quoteattr


def frames(seconds, fps):
    return max(0, round(seconds * fps))


def timecode(seconds, fps):
    n = frames(seconds, fps)
    f = n % fps
    s = n // fps
    return f'{s // 3600:02}:{s // 60 % 60:02}:{s % 60:02}:{f:02}'


def clock(seconds):
    ms = max(0, round(seconds * 1000))
    return f'{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


def edl(title, media_name, cuts, fps):
    """CMX3600. cuts: [{'start','end','label'}] — 렌더된 MP4 기준(편집본 시간)."""
    lines = [f'TITLE: {title}', 'FCM: NON-DROP FRAME', '']
    for i, cut in enumerate(cuts, 1):
        a, b = timecode(cut['start'], fps), timecode(cut['end'], fps)
        lines += [f'{i:03}  AX       AA/V  C        {a} {b} {a} {b}',
                  f'* FROM CLIP NAME: {media_name}', f'* COMMENT: {cut.get("label", "")}', '']
    return '\n'.join(lines)


def _t(seconds, fps):
    return f'{frames(seconds, fps)}/{fps}s'


def fcpxml(title, media_name, cuts, fps, width=1080, height=1920):
    """Final Cut Pro X 형식(FCPXML 1.8). 미디어는 같은 폴더의 파일을 다시 연결해야 할 수 있습니다."""
    total = max((c['end'] for c in cuts), default=0)
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<fcpxml version="1.8">', '  <resources>',
           f'    <format id="r1" name="FFVideoFormat{height}p{fps}" frameDuration="1/{fps}s" width="{width}" height="{height}"/>',
           f'    <asset id="r2" name={quoteattr(media_name)} src={quoteattr("./" + media_name)} start="0s" duration="{_t(total, fps)}" hasVideo="1" hasAudio="1" format="r1"/>',
           '  </resources>', '  <library>', f'    <event name={quoteattr(title)}>', f'      <project name={quoteattr(title)}>',
           f'        <sequence format="r1" duration="{_t(total, fps)}" tcStart="0s" tcFormat="NDF">', '          <spine>']
    for cut in cuts:
        out.append(f'            <asset-clip ref="r2" offset="{_t(cut["start"], fps)}" name={quoteattr(cut.get("label", "컷"))} '
                   f'start="{_t(cut["start"], fps)}" duration="{_t(cut["end"] - cut["start"], fps)}" format="r1"/>')
    out += ['          </spine>', '        </sequence>', '      </project>', '    </event>', '  </library>', '</fcpxml>', '']
    return '\n'.join(out)


def markers(cuts):
    return '\n'.join(f'{clock(c["start"])} - {clock(c["end"])}  컷 {i}  {c.get("label", "")}' for i, c in enumerate(cuts, 1)) + '\n'


def import_order(groups, edit_list):
    """컷별/제품별 MP4를 캡컷에 올릴 순서와 각 컷의 원본 구간."""
    lines = ['캡컷 가져오기 순서 (위에서 아래로 타임라인에 배치하세요)', '']
    for i, g in enumerate(groups, 1):
        lines.append(f'{i:02}. {g["file"]}  ({clock(g["end"] - g["start"])})  {g["label"]}')
        for e in edit_list:
            if g['start'] - 1e-6 <= e['edited_start'] < g['end'] - 1e-6:
                lines.append(f'      └ 원본 {e["source_name"]} {clock(e["original_start"])}~{clock(e["original_end"])}'
                             + (f' · 영상 {e["visual_source_name"]}' if e.get('visual_source_name') else ''))
    return '\n'.join(lines) + '\n'


def package(edit_list, groups, fps, base, width=1080, height=1920):
    """렌더 결과에 함께 넣을 파일들 {파일명: 내용}."""
    files = {'import-order.txt': import_order(groups, edit_list)}
    if len(groups) == 1:
        group = groups[0]
        cuts = [{'start': e['edited_start'], 'end': e['edited_end'], 'label': e['label']} for e in edit_list]
        files[f'{base}.edl'] = edl(base, group['file'], cuts, fps)
        files[f'{base}.fcpxml'] = fcpxml(base, group['file'], cuts, fps, width, height)
        files[f'{base}_cut-markers.txt'] = markers(cuts)
    return files
