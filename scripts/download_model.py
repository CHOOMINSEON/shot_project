"""Download model weights only; no user video/audio is sent to the model host."""
import argparse
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from studio.settings import DATA, MODEL_NAME
os.environ.setdefault('HF_HOME', str(DATA / 'huggingface'))

from faster_whisper.utils import download_model
from filelock import FileLock


def ensure_model(name=MODEL_NAME):
    if name not in ['tiny', 'base', 'small', 'medium']:
        raise ValueError('지원하지 않는 인식 모델입니다.')
    target = DATA / 'models' / f'whisper-{name}'
    with FileLock(DATA / 'models' / f'.{name}.lock'):
        if not all((target / file).is_file() and (target / file).stat().st_size for file in ['model.bin', 'config.json', 'tokenizer.json']):
            staging = DATA / 'models' / f'.{name}.download'
            download_model(name, output_dir=str(staging))
            # A partially downloaded directory is never used by the application.
            from faster_whisper import WhisperModel
            model = WhisperModel(str(staging), device='cpu', compute_type='int8', cpu_threads=2)
            del model
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default=MODEL_NAME, choices=['tiny', 'base', 'small', 'medium'])
    args = parser.parse_args()
    ensure_model(args.model)
    print(f'Local Whisper {args.model} model ready. Select with STUDIO_WHISPER_MODEL; restart to change models.')
