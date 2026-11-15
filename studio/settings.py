import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('STUDIO_DATA_DIR', str(ROOT / '.data'))).resolve()
MAX_FILE_BYTES = 10_000_000_000  # Decimal GB, not GiB.
MAX_INPUT_SECONDS = 7_200
MAX_OUTPUT_SECONDS = 1_800
CHUNK_BYTES = 8 * 1024 * 1024
WINDOW_SECONDS = 120
def _threads(name, default, ceiling):
    try:
        return max(1, min(ceiling, int(os.getenv(name) or default)))
    except ValueError:
        return default


# Windows는 논리 코어 수(SMT 포함)를 알려 주므로 절반을 물리 코어로 본다. 예: 6코어/12스레드 → 6.
_LOGICAL = os.cpu_count() or 2
CORES = max(2, _LOGICAL // 2) if _LOGICAL >= 4 else max(1, _LOGICAL)
THREADS = _threads('STUDIO_FFMPEG_THREADS', min(6, CORES), 12)          # 영상 합성(ffmpeg)
ASR_THREADS = _threads('STUDIO_ASR_THREADS', min(8, CORES), 16)          # 음성 인식(Whisper, CPU 사용 시)
VISION_THREADS = _threads('STUDIO_VISION_THREADS', min(6, CORES), 12)    # 장면·글자 인식
# 음성 인식 탐색 폭: 1=가장 빠름, 2=균형(기본), 5=가장 꼼꼼(느림)
ASR_BEAM = _threads('STUDIO_ASR_BEAM', 2, 10)
JOB_TIMEOUT = int(os.getenv('STUDIO_JOB_TIMEOUT_SECONDS', '86400'))
MODEL_NAME = os.getenv('STUDIO_WHISPER_MODEL', 'medium')
if MODEL_NAME not in ['tiny', 'base', 'small', 'medium', 'large-v3']:
    raise ValueError('STUDIO_WHISPER_MODEL must be tiny, base, small, medium or large-v3')
MODEL_DIR = DATA / 'models' / f'whisper-{MODEL_NAME}'
for directory in [DATA, DATA / 'assets', DATA / 'work', DATA / 'exports', DATA / 'models']:
    directory.mkdir(parents=True, exist_ok=True)
