#!/bin/sh
# Seed session from the host mount into /tmp (writable, SELinux-safe).
SESSION_SRC="/app/storage_state.json"
SESSION_DST="/tmp/storage_state.json"

if [ -r "$SESSION_SRC" ]; then
  cp "$SESSION_SRC" "$SESSION_DST"
  export PLAYWRIGHT_STORAGE_STATE="$SESSION_DST"
  echo "Session loaded: $SESSION_SRC -> $SESSION_DST"
elif [ -e "$SESSION_SRC" ]; then
  echo "WARNING: $SESSION_SRC is not readable inside the container." >&2
  echo "         On Fedora/Podman add ':z' to the volume in docker-compose.yml." >&2
fi

exec "$@"
