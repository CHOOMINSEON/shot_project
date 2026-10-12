#!/usr/bin/env bash
set -euo pipefail
cd /app
python - <<'PY'
import os
from studio.settings import MODEL_DIR
if len(os.getenv('STUDIO_PASSWORD', '')) < 12:
    raise SystemExit('소유자 비밀번호를 12자 이상으로 설정해 주세요.')
files = [MODEL_DIR / name for name in ['model.bin', 'config.json', 'tokenizer.json']]
if not all(path.is_file() and path.stat().st_size for path in files):
    import subprocess
    print('한국어 인식 모델을 처음 설치합니다. 인터넷 속도에 따라 시간이 걸립니다.', flush=True)
    subprocess.run(['python', 'scripts/download_model.py'], check=True)
from studio.worker import load_model
load_model()
print('한국어 모델 준비 완료.', flush=True)
PY
exec python -m uvicorn studio.app:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips='*'
