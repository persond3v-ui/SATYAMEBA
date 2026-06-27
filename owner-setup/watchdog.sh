#!/usr/bin/env bash
# SATYAMEBA — tamper watchdog (runs on the master via a systemd timer).
# Owner: Samaraho Mukherjee.
#
# Checks two anchors of owner control:
#   1. Tailscale is installed AND up (your out-of-band access).
#   2. An Owner account still exists in the database (you weren't removed).
#
# On tamper it SEALS immediately (halt + lock + alert). If auto-wipe is ARMED and
# tamper persists beyond the grace window, it escalates to an irreversible
# crypto-erase. The grace window exists so a transient blip (reboot, network
# flap, brief DB restart) can NEVER nuke real student research — you get alerts
# and can cancel from your phone over the tunnel.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
# shellcheck source=lib_crypto.sh
source ./lib_crypto.sh

CONF="${SAT_OWNER_CONF:-/etc/satyameba/owner.conf}"
[[ -f "$CONF" ]] && source "$CONF"          # OWNER_USERNAME, ARM_AUTOWIPE, GRACE_MINS, ALERT_CMD
ARM_AUTOWIPE="${ARM_AUTOWIPE:-0}"
GRACE_MINS="${GRACE_MINS:-30}"
TAMPER_MARK="$STATE_DIR/tamper_since"

tailscale_ok() { command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; }

owner_present() {
  # Query Postgres for at least one role='owner' user.
  local cid n
  cid="$(docker ps --format '{{.ID}} {{.Image}}' | awk '/postgres/ {print $1; exit}')"
  [[ -z "$cid" ]] && return 0   # DB not running (e.g. already sealed) — don't double-trip
  n="$(docker exec "$cid" psql -tA -U "${POSTGRES_USER:-satyameba}" -d "${POSTGRES_DB:-satyameba}" \
        -c "select count(*) from users where role='owner';" 2>/dev/null | tr -d '[:space:]')"
  [[ "${n:-0}" -ge 1 ]]
}

mkdir -p "$STATE_DIR"

if tailscale_ok && owner_present; then
  rm -f "$TAMPER_MARK" 2>/dev/null || true   # all clear
  exit 0
fi

# --- tamper detected ---
reason="$( { tailscale_ok || echo 'tailscale-missing'; }; { owner_present || echo 'owner-removed'; } )"
log "TAMPER detected: ${reason}"
[[ -f "$TAMPER_MARK" ]] || date +%s > "$TAMPER_MARK"
seal   # immediate: halt + lock + alert

if [[ "$ARM_AUTOWIPE" == "1" ]]; then
  since="$(cat "$TAMPER_MARK" 2>/dev/null || echo "$(date +%s)")"
  elapsed_min=$(( ( $(date +%s) - since ) / 60 ))
  remaining=$(( GRACE_MINS - elapsed_min ))
  if (( elapsed_min >= GRACE_MINS )); then
    alert "Auto-wipe grace (${GRACE_MINS}m) EXCEEDED — crypto-erasing now."
    wipe
  else
    alert "Tamper persists; auto-wipe in ${remaining}m unless restored. Cancel via the tunnel."
  fi
else
  alert "Auto-wipe NOT armed — staying sealed. Restore owner/Tailscale, or run panic.sh to wipe."
fi
