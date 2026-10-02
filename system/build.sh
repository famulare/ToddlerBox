#!/bin/bash
# Linux x86-64 builder; Docker also supports this on an x86 Linux VM.
set -euo pipefail
cd "$(dirname "$0")/.."
source system/versions.env
command -v docker >/dev/null
command -v uv >/dev/null
[[ $(uname -m) == x86_64 ]] || { echo 'Use an x86-64 Linux builder.' >&2; exit 1; }
mkdir -p build
export BUILDX_CONFIG=${BUILDX_CONFIG:-$PWD/build/buildx}
ca_bundle=${TODDLERBOX_BUILD_CA:-/etc/ssl/certs/ca-certificates.crt}
release_id=$(uv run --no-project --python /usr/bin/python3 system/source-id.py)
build_args=(--platform linux/amd64 --secret "id=proxy_ca,src=$ca_bundle"
            --build-arg "UBUNTU_IMAGE=$UBUNTU_IMAGE" --build-arg "UBUNTU_SNAPSHOT=$UBUNTU_SNAPSHOT")
docker build "${build_args[@]}" -f system/Dockerfile.base -t toddlerbox-os-base .
docker build "${build_args[@]}" -f system/Dockerfile.tools -t toddlerbox-image-tools .
docker build --platform linux/amd64 --secret "id=proxy_ca,src=$ca_bundle" \
    --build-arg "UV_IMAGE=$UV_IMAGE" --build-arg "RELEASE_ID=$release_id" \
    -f system/Dockerfile.release -t "toddlerbox-release:$release_id" .
if [[ ${1:-} == --release-only ]]; then
    printf 'Built source release: %s\n' "$release_id"
    exit 0
fi
container=$(docker create "toddlerbox-release:$release_id")
trap 'docker rm "$container" >/dev/null' EXIT
docker export "$container" | docker run --rm -i --network=none \
    -v "$PWD/build:/build" -v "$PWD:/source:ro" toddlerbox-image-tools \
    bash -c 'rm -rf /build/rootfs; mkdir -p /build/rootfs; tar -xpf - -C /build/rootfs'
# With Docker's vfs driver, the export container consumes another full rootfs.
# Release that copy before assembling the disk to bound peak storage use.
docker rm "$container" >/dev/null
trap - EXIT
docker run --rm --network=none -v "$PWD/build:/build" -v "$PWD:/source:ro" \
    toddlerbox-image-tools \
    bash -c 'cp /source/system/make-images.sh /tmp/make-images.sh; bash /tmp/make-images.sh'
printf 'Source release: %s\n' "$release_id"
