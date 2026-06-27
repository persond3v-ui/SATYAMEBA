#!/usr/bin/env bash
# SATYAMEBA — owner panic switch. Run over the Tailscale tunnel when you decide
# the machines are compromised/seized. IRREVERSIBLE crypto-erase + full takedown.
# Owner: Samaraho Mukherjee.
#
#   sudo ./owner-setup/panic.sh --yes-destroy-everything
#
# Optionally sweep workers too (shred any local key caches) if you pass
# --workers "host1 host2 host3" (reached over the tunnel/VLAN by SSH).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib_crypto.sh
source ./lib_crypto.sh

CONFIRM=0; WORKERS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes-destroy-everything) CONFIRM=1 ;;
    --workers) WORKERS="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done

if [[ $CONFIRM -ne 1 ]]; then
  cat >&2 <<'MSG'
REFUSING: panic.sh permanently destroys all SATYAMEBA data via crypto-erase.
This cannot be undone. Re-run with --yes-destroy-everything if you are certain.
MSG
  exit 1
fi

log "PANIC initiated by owner."
wipe
for h in $WORKERS; do
  log "PANIC: sweeping worker $h"
  ssh -o StrictHostKeyChecking=accept-new "$h" \
    'sudo find /srv/satyameba -name "gocryptfs.conf" -exec shred -fuz {} \; ; sudo rm -rf /srv/satyameba/keystore' \
    2>/dev/null || log "  (could not reach $h)"
done
log "PANIC complete. Everything is down and unrecoverable."
