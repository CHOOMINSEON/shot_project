"""Download model weights only; no user video/audio is sent to the model host."""
import argparse
import os
import sys
import fcntl
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from studio.settings import DATA, MODEL_NAME
os.environ.setdefault('HF_HOME', str(DATA / 'huggingface'))

from faster_whisper.utils import download_model

parser = argparse.ArgumentParser()
parser.add_argument('--model', default=MODEL_NAME, choices=['tiny', 'base', 'small', 'medium'])
args = parser.parse_args()
target = DATA / 'models' / f'whisper-{args.model}'
with (DATA / 'models' / f'.{args.model}.lock').open('w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    if not all((target / name).is_file() and (target / name).stat().st_size for name in ['model.bin', 'config.json', 'tokenizer.json']):
        staging = DATA / 'models' / f'.{args.model}.download'
        download_model(args.model, output_dir=str(staging))
        # A partially downloaded directory is never used by the application.
        from faster_whisper import WhisperModel
        model = WhisperModel(str(staging), device='cpu', compute_type='int8', cpu_threads=2)
        del model
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
print(f'Local Whisper {args.model} model ready. Select with STUDIO_WHISPER_MODEL; restart to change models.')
