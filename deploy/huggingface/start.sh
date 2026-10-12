#!/usr/bin/env bash
set -euo pipefail
cd /app
python - <<'PY'
import os
from pathlib import Path
from studio.settings import MODEL_DIR

password = os.getenv('STUDIO_PASSWORD', '')
if len(password) < 12:
    raise SystemExit('Space Settings에서 STUDIO_PASSWORD Secret을 12자 이상으로 설정해 주세요. 비밀번호 값은 로그에 출력하지 않습니다.')
files = [MODEL_DIR / name for name in ['model.bin', 'config.json', 'tokenizer.json']]
if not all(path.is_file() and path.stat().st_size for path in files):
    import subprocess
    subprocess.run(['python', 'scripts/download_model.py'], check=True)
from studio.worker import load_model
load_model()
print('한국어 모델 준비 완료. 소유자 로그인으로 작업실에 접근할 수 있습니다.')
PY
exec python -m uvicorn studio.app:app --host 0.0.0.0 --port 8000 --workers 1 --forwarded-allow-ips='*'
