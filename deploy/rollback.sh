#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
release="${1:-}"
if [[ ! "$release" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]; then
  echo '사용법: bash deploy/rollback.sh 이전_릴리스_이름' >&2
  exit 1
fi
settings_file="${STUDIO_PRODUCTION_ENV:-deploy/.env.production}"
# Reuse the original data volume and password. Never rebuild or delete originals on rollback.
STUDIO_RELEASE="$release" docker compose --env-file "$settings_file" -f deploy/production.yaml \
  up -d --no-build --wait studio
echo '이전 앱 이미지로 복원했습니다. 공개 주소에서 로그인과 기존 프로젝트를 확인해 주세요.'
