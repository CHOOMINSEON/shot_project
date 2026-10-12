#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Bind locally by default; use an HTTPS reverse proxy for remote owner-only access.
exec .venv/bin/python -m uvicorn studio.app:app --host "${STUDIO_HOST:-127.0.0.1}" --port "${STUDIO_PORT:-8000}" --workers 1
