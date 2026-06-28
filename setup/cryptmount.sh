#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — per-user gocryptfs mount manager (host side).
#
#   cryptmount.sh init  <sid>     # create a user's encrypted cipherdir
#   cryptmount.sh up    <sid>     # mount cipher -> plaintext view (idempotent)
#   cryptmount.sh ensure <sid>    # init if needed, then up
#   cryptmount.sh down  <sid>     # unmount the plaintext view (data stays encrypted)
#   cryptmount.sh all-up          # mount every existing user (boot-time)
#
# Each user's encryption key is derived from the owner root KEK (owner-setup
# keystore) as HMAC-SHA256(KEK, "u-<sid>"), so:
#   * every user has a distinct key,
#   * all keys are anchored to the one KEK, and
#   * the owner crypto-erase (shred the KEK + gocryptfs.conf) makes every user's
#     data permanently unrecoverable instantly.
#
# The host disk/NFS only ever holds CIPHERTEXT under $SAT_CIPHER_BASE; the
# decrypted view under $SAT_PLAIN_BASE is what the notebook container bind-mounts.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Pull in KEYSTORE / DATAROOT / log() without the owner-setup side effects.
KEYSTORE="${SAT_KEYSTORE:-/srv/satyameba/keystore}"
DATAROOT="${SAT_DATAROOT:-/srv/satyameba}"
CIPHER_BASE="${SAT_CIPHER_BASE:-$DATAROOT/cipher}"
PLAIN_BASE="${SAT_PLAIN_BASE:-$DATAROOT/plain}"
NB_UID="${SAT_NB_UID:-1000}"; NB_GID="${SAT_NB_GID:-100}"
log() { printf '%s [cryptmount] %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }

command -v gocryptfs >/dev/null 2>&1 || { echo "gocryptfs not installed — run setup/gocryptfs_setup.sh"; exit 1; }

_passfile() {  # derive a per-user passphrase from the KEK; echo a temp passfile path
  local sid="$1"
  [[ -f "$KEYSTORE/kek.key" ]] || { echo "no root KEK at $KEYSTORE/kek.key (run gocryptfs_setup.sh)" >&2; return 1; }
  local kekhex pass pf
  kekhex="$(od -An -v -tx1 "$KEYSTORE/kek.key" | tr -d ' \n')"
  pass="$(printf '%s' "u-$sid" | openssl dgst -sha256 -mac HMAC -macopt "hexkey:$kekhex" | awk '{print $NF}')"
  pf="$(mktemp)"; printf '%s' "$pass" > "$pf"; echo "$pf"
}

cmd_init() {
  local sid="$1" cipher="$CIPHER_BASE/u-$1"
  [[ -f "$cipher/gocryptfs.conf" ]] && return 0
  mkdir -p "$cipher"
  local pf; pf="$(_passfile "$sid")"
  gocryptfs -init -q -passfile "$pf" "$cipher"; rm -f "$pf"
  log "initialised cipherdir for u-$sid"
}

cmd_up() {
  local sid="$1" cipher="$CIPHER_BASE/u-$1" plain="$PLAIN_BASE/u-$1"
  cmd_init "$sid"
  mkdir -p "$plain"
  mountpoint -q "$plain" 2>/dev/null && return 0
  local pf; pf="$(_passfile "$sid")"
  gocryptfs -q -passfile "$pf" -allow_other "$cipher" "$plain"; rm -f "$pf"
  chown "$NB_UID:$NB_GID" "$plain" 2>/dev/null || true
  log "mounted u-$sid"
}

cmd_down() {
  local plain="$PLAIN_BASE/u-$1"
  mountpoint -q "$plain" 2>/dev/null || return 0
  fusermount -u "$plain" 2>/dev/null || umount -l "$plain" 2>/dev/null || true
  log "unmounted u-$1"
}

cmd_all_up() {
  shopt -s nullglob
  for d in "$CIPHER_BASE"/u-*; do
    [[ -d "$d" ]] && cmd_up "${d##*/u-}"
  done
}

case "${1:-}" in
  init)        cmd_init "$2" ;;
  up|ensure)   cmd_up "$2" ;;
  down)        cmd_down "$2" ;;
  all-up)      cmd_all_up ;;
  *) echo "usage: cryptmount.sh {init|up|ensure|down|all-up} [sid]"; exit 1 ;;
esac
