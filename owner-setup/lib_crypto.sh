#!/usr/bin/env bash
# SATYAMEBA — owner crypto/keystore library (sourced by the owner-setup scripts).
# Owner: Samaraho Mukherjee.
#
# Model: a single root Key-Encryption-Key (KEK) anchors all per-user at-rest
# encryption (gocryptfs cipherdirs are wrapped under it). "Crypto-erase" = shred
# the KEK + every cipherdir's key file, which makes terabytes of ciphertext
# permanently unrecoverable *instantly* — the safe form of a secure wipe (no
# slow overwrite, no touching anything off-box).
#
# NOTE: these operate on the MASTER, where (in NFS storage mode) all per-user
# data and keys live and are exported to workers — so a master-side erase is
# cluster-wide. Verify on your real hardware before relying on it.
set -euo pipefail

KEYSTORE="${SAT_KEYSTORE:-/srv/satyameba/keystore}"
DATAROOT="${SAT_DATAROOT:-/srv/satyameba}"
STATE_DIR="${SAT_STATE_DIR:-/run/satyameba}"
LOG="${SAT_OWNER_LOG:-/var/log/satyameba-owner.log}"

log()   { mkdir -p "$(dirname "$LOG")" 2>/dev/null || true; printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG" >&2; }
alert() {  # alert "message" — fire ALERT_CMD (webhook/SSH/mail) if configured
  local msg="$1"
  log "ALERT: $msg"
  [[ -n "${ALERT_CMD:-}" ]] && SAT_ALERT_MSG="$msg" bash -c "$ALERT_CMD" || true
}

repo_dir() { cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd; }

stack_down() {
  # Stop the platform (swarm stack or compose). Non-destructive.
  if docker info 2>/dev/null | grep -q "Swarm: active"; then
    docker stack rm satyameba 2>/dev/null || true
  fi
  ( cd "$(repo_dir)" && docker compose down 2>/dev/null ) || true
}

keystore_init() {
  mkdir -p "$KEYSTORE"; chmod 700 "$KEYSTORE"
  if [[ ! -f "$KEYSTORE/kek.key" ]]; then
    head -c 32 /dev/urandom > "$KEYSTORE/kek.key"
    chmod 600 "$KEYSTORE/kek.key"
    log "keystore: generated root KEK at $KEYSTORE/kek.key"
  else
    log "keystore: KEK already present"
  fi
}

seal() {
  # Make data inaccessible NOW without destroying it: stop the stack and unmount
  # any plaintext gocryptfs mounts. Recoverable by the owner (KEK preserved).
  log "SEAL: stopping platform + unmounting plaintext views"
  stack_down
  for m in $(mount 2>/dev/null | awk '/fuse.gocryptfs/ {print $3}'); do
    fusermount -u "$m" 2>/dev/null || umount -l "$m" 2>/dev/null || true
  done
  alert "SATYAMEBA SEALED — platform halted, encrypted data locked. Investigate."
}

crypto_erase() {
  # Permanent: shred the KEK and every cipherdir master-key file. After this the
  # ciphertext can never be decrypted. THIS IS IRREVERSIBLE.
  log "WIPE: crypto-erasing keys (irreversible)"
  shred -fuz "$KEYSTORE/kek.key" 2>/dev/null || rm -f "$KEYSTORE/kek.key"
  # gocryptfs stores the wrapped master key in gocryptfs.conf — shredding it
  # renders that cipherdir undecryptable.
  find "$DATAROOT" -name 'gocryptfs.conf' -exec shred -fuz {} \; 2>/dev/null || true
  rm -rf "$KEYSTORE" 2>/dev/null || true
}

wipe() {
  # Full takedown: crypto-erase keys, stop everything, drop platform volumes.
  crypto_erase
  stack_down
  # Remove platform/data volumes (DB, hub, per-user named volumes).
  docker volume ls -q 2>/dev/null | grep -E 'satyameba|pgdata|hubdata|grafana|prometheus' \
    | xargs -r docker volume rm -f 2>/dev/null || true
  mkdir -p "$STATE_DIR"; date -u +%FT%TZ > "$STATE_DIR/WIPED" 2>/dev/null || true
  alert "SATYAMEBA WIPED — keys crypto-erased, platform + volumes destroyed."
  log "WIPE complete."
}
