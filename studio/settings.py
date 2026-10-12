import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('STUDIO_DATA_DIR', str(ROOT / '.data'))).resolve()
MAX_FILE_BYTES = 10_000_000_000  # Decimal GB, not GiB.
MAX_INPUT_SECONDS = 7_200
MAX_OUTPUT_SECONDS = 1_800
CHUNK_BYTES = 8 * 1024 * 1024
WINDOW_SECONDS = 120
THREADS = max(1, min(4, int(os.getenv('STUDIO_FFMPEG_THREADS', '2'))))
JOB_TIMEOUT = int(os.getenv('STUDIO_JOB_TIMEOUT_SECONDS', '86400'))
MODEL_NAME = os.getenv('STUDIO_WHISPER_MODEL', 'medium')
if MODEL_NAME not in ['tiny', 'base', 'small', 'medium']:
    raise ValueError('STUDIO_WHISPER_MODEL must be tiny, base, small or medium')
MODEL_DIR = DATA / 'models' / f'whisper-{MODEL_NAME}'
for directory in [DATA, DATA / 'assets', DATA / 'work', DATA / 'exports', DATA / 'models']:
    directory.mkdir(parents=True, exist_ok=True)
