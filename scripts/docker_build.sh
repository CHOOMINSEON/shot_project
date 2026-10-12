#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Standard BuildKit proxy args are not written to the image. The CA bundle is public trust data.
export DOCKER_CONFIG="${STUDIO_DOCKER_CONFIG:-$PWD/.data/docker}"
args=(--build-arg HTTP_PROXY --build-arg HTTPS_PROXY --build-arg NO_PROXY --network=host)
if [ -n "${SSL_CERT_FILE:-}" ] && [ -f "$SSL_CERT_FILE" ]; then
  args+=(--secret "id=build_ca,src=$SSL_CERT_FILE")
fi
docker build "${args[@]}" -t iyoring-cut-studio:local .
