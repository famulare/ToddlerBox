#!/bin/bash
# App-only release for existing Ubuntu 24.04 x86-64 appliances.
# Reuses the image tools' Ubuntu Python ABI; never copies a developer virtualenv.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ $(uname -m) == x86_64 ]] || { echo 'Use an x86-64 Linux builder.' >&2; exit 1; }
output=${1:-build/app-update}
mkdir -p "$output"
output=$(realpath "$output")
release_id=$(uv run --frozen python system/source-id.py)
release="$output/releases/$release_id"
[[ ! -e "$release" ]] || { echo 'Use a new build directory.' >&2; exit 1; }
mkdir -p "$release"
cp -a src assets pyproject.toml uv.lock README.md LICENSE config.yaml data-schema.json "$release/"
find "$release" -type d \( -name __pycache__ -o -name '*.egg-info' \) -prune -exec rm -rf {} +
ca_bundle=${TODDLERBOX_BUILD_CA:-/etc/ssl/certs/ca-certificates.crt}
uv_binary=$(realpath "$(command -v uv)")
docker run --rm --read-only --tmpfs /tmp:rw,size=256m \
    --user "$(id -u):$(id -g)" \
    -v "$release:/opt/toddlerbox/releases/$release_id" \
    -v "$uv_binary:/run/uv:ro" -v "$ca_bundle:/run/proxy-ca.pem:ro" \
    -v "$PWD/system/normalize_venv.py:/run/normalize_venv.py:ro" \
    -w "/opt/toddlerbox/releases/$release_id" \
    -e SSL_CERT_FILE=/run/proxy-ca.pem -e UV_CACHE_DIR=/tmp/uv-cache \
    -e UV_PYTHON_DOWNLOADS=never \
    toddlerbox-image-tools sh -ec '/run/uv sync --frozen --no-dev --python /usr/bin/python3; /run/uv run --no-project --python /usr/bin/python3 /run/normalize_venv.py .venv'
# Match configure-rootfs.sh: a private builder umask must not make public app
# code unreadable to the child, and dependency locks must not be world writable.
chmod -R a+rX,go-w "$release"
# Root ownership is set in the archive, as for image-built app releases.
tar --sort=name --owner=0 --group=0 -czf "$output/toddlerbox-app-$release_id.tar.gz" \
    -C "$output/releases" "$release_id"
sha256sum "$output/toddlerbox-app-$release_id.tar.gz" >"$output/APP-SHA256SUMS"
printf '%s\n' "$release_id" >"$output/release-id"
printf 'Built Ubuntu app release: %s\n' "$release_id"
