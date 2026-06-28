#!/usr/bin/env bash
# set_env.sh KEY VALUE [FILE]  — idempotently set-or-append KEY=VALUE in an env file.
set -euo pipefail
k="$1"; v="$2"; f="${3:-.env}"
touch "$f"
if grep -q "^${k}=" "$f"; then
  sed -i "s|^${k}=.*|${k}=${v}|" "$f"
else
  printf '%s=%s\n' "$k" "$v" >> "$f"
fi
