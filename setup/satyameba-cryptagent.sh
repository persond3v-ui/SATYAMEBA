#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — gocryptfs mount agent (runs on each node as a systemd service).
#
# Nothing inside a container can mount on the host, so this host-side agent does
# it: at boot it mounts every existing user's encrypted view, then it watches
# Docker for notebook containers starting and mounts that user's view on demand
# (new users included). The notebook container bind-mounts the decrypted view.
#
# Keys come from the owner KEK (see cryptmount.sh). Unmounting on stop is left to
# the owner seal/wipe path so a quick relaunch never races an unmounted dir;
# while the host is powered on the views are mounted (the documented in-use
# limitation — a powered-off / pulled disk is always ciphertext).
# ===========================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CM="$ROOT/setup/cryptmount.sh"
log() { printf '%s [cryptagent] %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

# 1) Boot-time: mount everything that already exists.
bash "$CM" all-up || log "all-up returned non-zero (continuing)"
log "agent up; watching docker events for notebook spawns"

# 2) On-demand: mount a user's view the moment their notebook container is created.
#    Containers are labelled satyameba.sid=<sid> by the spawner.
docker events --filter 'event=create' --filter 'label=satyameba.sid' \
  --format '{{index .Actor.Attributes "satyameba.sid"}}' 2>/dev/null |
while read -r sid; do
  [[ -n "$sid" ]] || continue
  bash "$CM" ensure "$sid" && log "ensured mount for u-$sid" || log "mount failed for u-$sid"
done
