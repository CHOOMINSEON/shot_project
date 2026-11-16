import shutil
import subprocess

import pytest

from studio import media, timeline


def test_caption_times_follow_output_speed():
    items = [{'text': '가', 'start': 1.4, 'end': 2.8}]
    assert timeline.output_speed({'speed': 1.4}) == 1.4
    assert timeline.output_speed({}) == 1 and timeline.output_speed({'speed': 9}) == 1 and timeline.output_speed({'speed': 'x'}) == 1
    scaled = timeline.scale_captions(items, 1.4)
    assert abs(scaled[0]['start'] - 1.0) < 1e-9 and abs(scaled[0]['end'] - 2.0) < 1e-9
    assert timeline.scale_captions(items, 1) is items
    assert timeline.render_signature({'clips': [], 'speed': 1.4}) != timeline.render_signature({'clips': []})
    assert timeline.render_signature({'clips': [], 'speed': 1}) == timeline.render_signature({'clips': []})
    assert media.atempo_chain(1.4) == 'atempo=1.400000'


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='ffmpeg 없음')
def test_speed_up_shortens_real_video_and_keeps_audio(tmp_path):
    clip = tmp_path / 'a.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=180x320:rate=30:duration=7',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=7', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', '-shortest', str(clip)], check=True)
    info = media.speed_up(clip, 1.4, tmp_path / 'work')
    assert abs(info['duration'] - 5.0) < .15, info['duration']
    assert info['has_audio'] and info['has_video']
