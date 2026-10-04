#!/bin/bash
# Lower peak storage on vfs builders; identical package/configuration inputs.
set -euo pipefail
cd "$(dirname "$0")/.."
source system/versions.env
[[ $(uname -m) == x86_64 ]] || { echo 'Use an x86-64 Linux builder.' >&2; exit 1; }
export UV_CACHE_DIR=${UV_CACHE_DIR:-/tmp/toddlerbox-uv-cache}
export BUILDX_CONFIG=${BUILDX_CONFIG:-$PWD/build/buildx}
output=${TODDLERBOX_BUILD_DIR:-$PWD/build/next-image}
archive=${TODDLERBOX_DOCKER_ARCHIVE:-/tmp/toddlerbox-image.tar.gz}
[[ ! -e $output && ! -e $archive ]] || { echo 'Preserve/move existing output/archive first.' >&2; exit 1; }
mkdir -p "$output"
release_id=$(uv run --no-project --python /usr/bin/python3 system/source-id.py)
args=(--platform linux/amd64 --secret "id=proxy_ca,src=${TODDLERBOX_BUILD_CA:-/etc/ssl/certs/ca-certificates.crt}"
      --build-arg "UBUNTU_IMAGE=$UBUNTU_IMAGE" --build-arg "UBUNTU_SNAPSHOT=$UBUNTU_SNAPSHOT")
docker build "${args[@]}" --target toddlerbox-cage-builder -f system/Dockerfile.base -t toddlerbox-cage-builder .
docker build "${args[@]}" -f system/Dockerfile.tools -t toddlerbox-image-tools .
docker build "${args[@]}" --build-arg "UV_IMAGE=$UV_IMAGE" --build-arg "RELEASE_ID=$release_id" \
    -f system/Dockerfile.compact -t "toddlerbox-compact:$release_id" .
docker image save "toddlerbox-compact:$release_id" | gzip -1 >"$archive"
docker run --rm --network=none -v "$output:/build" -v "$PWD:/source:ro" -v "$archive:/tmp/image.tar.gz:ro" \
    toddlerbox-image-tools python3 /source/system/extract-docker-save.py /tmp/image.tar.gz /build/rootfs
rm "$archive"
# This removes only the just-built image tag; retained bases/checkpoints are files.
docker image rm "toddlerbox-compact:$release_id"
if [[ ${TODDLERBOX_PRUNE_BUILD_CACHE:-0} == 1 ]]; then
    docker builder prune -f  # Explicit opt-in; affects unused build cache only.
fi
docker run --rm --network=none -e TODDLERBOX_DISCARD_ROOTFS=1 -v "$output:/build" -v "$PWD:/source:ro" \
    toddlerbox-image-tools bash /source/system/make-images.sh
printf 'Source release: %s\n' "$release_id"
