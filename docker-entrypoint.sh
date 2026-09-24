#!/bin/sh
set -eu

# Railway mounts persistent volumes as root after the image has been built.
# Fix only the mount-point ownership, then drop privileges before Python starts.
if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown researcher:researcher /data
    exec gosu researcher "$@"
fi

exec "$@"
