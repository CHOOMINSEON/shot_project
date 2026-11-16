"""장면 분석 속도 개선 점검(가짜 영상·가짜 모델): 같은 장면에서는 글자 인식을 반복하지 않고, 장면이 바뀌면 다시 한다."""
import os
import sys
import tempfile
import types
from fractions import Fraction

import numpy as np
from PIL import Image

os.environ.setdefault('STUDIO_DATA_DIR', tempfile.mkdtemp(prefix='scene-speed-'))


class FakeFrame:
    def __init__(self, index, fps, color):
        self.pts, self.time_base, self.duration, self.color = index, Fraction(1, fps), 1, color

    def reformat(self, width, height, format):
        return types.SimpleNamespace(to_ndarray=lambda: np.full((height, width, 3), self.color, dtype=np.uint8))

    def to_image(self):
        return Image.new('RGB', (1080, 1920), (self.color, self.color, self.color))


class FakeContainer:
    def __init__(self, frames):
        stream = types.SimpleNamespace(start_time=0, time_base=Fraction(1, 30), codec_context=types.SimpleNamespace(thread_count=0))
        self.streams = types.SimpleNamespace(video=[stream])
        self.frames = frames

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def decode(self, stream):
        return iter(self.frames)

    def seek(self, *a, **k):
        pass


class FakeModel:
    def __init__(self):
        self.reads = 0
        self.images = 0

    def texts(self, texts):
        rng = np.random.default_rng(len(texts))
        return rng.normal(size=(len(texts), 8)).astype(np.float32) * 0 + .1

    def image(self, image):
        self.images += 1
        return np.asarray([1, 0, 0, 0, 0, 0, 0, 0] if np.asarray(image)[0, 0, 0] < 100 else [0, 1, 0, 0, 0, 0, 0, 0], dtype=np.float32)

    def read(self, image):
        self.reads += 1
        assert max(image.size) <= 1024, image.size   # 글자 인식 입력은 줄여서 넣는다
        return [{'text': '제품명', 'confidence': .9, 'box': [[10, 10], [60, 10], [60, 40], [10, 40]]}]


def run(colors_by_second, monkeypatch):
    for name in ['httpx', 'filelock']:   # 이 점검은 모델 내려받기를 쓰지 않는다(설치돼 있으면 그대로 사용)
        try:
            __import__(name)
        except ImportError:
            monkeypatch.setitem(sys.modules, name, types.SimpleNamespace(Client=None, Timeout=None, FileLock=None))
    from studio import scene_index, scene_models
    model = FakeModel()
    fps = 30
    frames = [FakeFrame(s * fps + k, fps, color) for s, color in enumerate(colors_by_second) for k in range(fps)]
    monkeypatch.setitem(sys.modules, 'av', types.SimpleNamespace(open=lambda *a, **k: FakeContainer(frames)))   # 다른 점검에 영향 없도록 되돌려짐
    monkeypatch.setattr(scene_models, 'load', lambda check=None, progress=None: model)
    return scene_index, model, len(colors_by_second)


def test_static_scene_reads_text_once_and_new_scene_reads_again(monkeypatch):
    scene_index, model, seconds = run([20] * 20 + [220] * 10, monkeypatch)
    ident = 'speed-asset'
    folder = scene_index.DATA / 'assets' / ident
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'original').write_bytes(b'x')
    asset = {'id': ident, 'name': 't.mp4', 'metadata': {'duration': seconds, 'has_video': True, 'rotation': 0}, 'analysis': {'words': []}}
    messages = []
    result = scene_index.build(asset, progress=lambda v, m: messages.append(m))
    assert result['complete'] and result['count'] >= 20
    assert model.reads <= result['count'] // 3, (model.reads, result['count'])   # 같은 장면은 5초마다만 다시 읽음(전엔 분석한 프레임마다 읽음)
    assert model.reads >= 2                    # 장면이 바뀌면 다시 읽는다
    assert any('남은 시간' in m for m in messages)


def test_fast_mode_skips_text_reading_but_still_indexes_scenes(monkeypatch):
    scene_index, model, seconds = run([20] * 10 + [220] * 10, monkeypatch)
    ident = 'fast-asset'
    folder = scene_index.DATA / 'assets' / ident
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'original').write_bytes(b'x')
    asset = {'id': ident, 'name': 't.mp4', 'metadata': {'duration': seconds, 'has_video': True, 'rotation': 0}, 'analysis': {'words': []}}
    result = scene_index.build(asset, fast=True)
    assert result['complete'] and result['count'] >= 15
    assert model.reads == 0                       # 글자 인식 생략
    rows, vectors = scene_index.load(ident)
    assert len(rows) == result['count'] and vectors is not None   # 장면 후보는 그대로 만든다
    assert len({r['shot'] for r in rows}) == 2    # 장면 전환도 잡는다
    before = model.images
    assert scene_index.build(asset, fast=False)['count'] > 0 and model.reads > 0   # 정밀 분석을 요청하면 다시 만든다
    assert model.images > before
