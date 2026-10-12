#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
settings_file="${STUDIO_PRODUCTION_ENV:-deploy/.env.production}"
if [ ! -f "$settings_file" ]; then
  echo '배포 서버의 deploy/.env.production에 도메인·릴리스·소유자 비밀번호를 설정해 주세요.' >&2
  exit 1
fi
compose=(docker compose --env-file "$settings_file" -f deploy/production.yaml)
"${compose[@]}" config --quiet
"${compose[@]}" build studio
"${compose[@]}" up -d --wait studio
"${compose[@]}" exec -T studio python scripts/download_model.py
"${compose[@]}" up -d caddy
domain="$("${compose[@]}" exec -T caddy printenv STUDIO_DOMAIN)"
if [[ ! "$domain" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]]; then
  echo '도메인에는 프로토콜·포트·경로를 포함하지 마세요.' >&2
  exit 1
fi
# HTTPS verification stays enabled. DNS must point to this host and ports 80/443 must be open.
response="$(curl --fail --silent --show-error --retry 10 --retry-delay 3 --retry-all-errors \
  --connect-timeout 5 --max-time 10 "https://$domain/api/health")"
printf '%s' "$response" | "${compose[@]}" exec -T studio python -c \
  'import json,sys; value=json.load(sys.stdin); assert value.get("status")=="ok" and value.get("app")=="신상집착 컷 스튜디오", "공개 주소에서 다른 앱이 응답했습니다."'
printf '\n공개 HTTPS 응답 확인: https://%s\n' "$domain"
