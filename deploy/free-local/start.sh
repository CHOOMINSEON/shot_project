#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if ! docker info >/dev/null 2>&1; then
  echo 'Docker를 먼저 실행하고 준비될 때까지 기다려 주세요.' >&2
  exit 1
fi
docker compose version >/dev/null
command -v curl >/dev/null
rm -f public-url.txt
if [ ! -f .env ]; then
  read -r -s -p '로그인 비밀번호를 정하세요 (영문/숫자 12자 이상): ' password
  printf '\n'
  if [[ ! "$password" =~ ^[A-Za-z0-9]{12,}$ ]]; then
    echo '비밀번호는 영문/숫자로 12자 이상 입력해 주세요.' >&2
    exit 1
  fi
  (umask 077; printf 'STUDIO_PASSWORD=%s\n' "$password" > .env)
  unset password
fi
echo '앱과 한국어 모델을 준비합니다. 첫 설치는 수 분 이상 걸릴 수 있습니다.'
docker compose --env-file .env -f compose.yaml up -d --build
echo '무료 임시 공개 주소를 확인합니다. PC와 Docker가 켜져 있어야 접속됩니다.'
deadline=$((SECONDS + 120))
while (( SECONDS < deadline )); do
  url=$(docker compose --env-file .env -f compose.yaml logs --no-color --tail 80 tunnel 2>&1 | sed -nE 's@.*(https://[a-z0-9-]+\.trycloudflare\.com).*@\1@p' | tail -1)
  if [ -n "$url" ]; then
    if response=$(curl --fail --silent --show-error --connect-timeout 5 --max-time 10 "$url/api/health" 2>/dev/null) &&
       [[ "$response" == *'"status":"ok"'* && "$response" == *'신상집착 컷 스튜디오'* ]]; then
      printf '%s\n' "$url" > public-url.txt
      printf '접속 확인 완료: %s\n방금 정한 비밀번호로 로그인하세요. 종료는 bash stop.sh를 실행하세요.\n' "$url"
      exit 0
    fi
  fi
  sleep 2
done
echo '공개 연결을 확인하지 못했습니다. 터널 로그와 인터넷 연결을 확인해 주세요. 이전 주소는 유효하지 않을 수 있습니다.' >&2
exit 1
