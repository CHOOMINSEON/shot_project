#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/.data/pip-cache}"
mkdir -p "$PIP_CACHE_DIR"
command -v ffmpeg >/dev/null || { echo 'FFmpeg with libx264, AAC and zscale is required. See README.md.' >&2; exit 1; }
command -v ffprobe >/dev/null
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock
model_dir="$(.venv/bin/python -c 'from studio.settings import MODEL_DIR; print(MODEL_DIR)')"
if [ ! -f "$model_dir/model.bin" ] || [ ! -f "$model_dir/config.json" ]; then
  .venv/bin/python scripts/download_model.py
fi
.venv/bin/python -c 'from studio.worker import load_model; load_model(); print("Local speech model ready")'
