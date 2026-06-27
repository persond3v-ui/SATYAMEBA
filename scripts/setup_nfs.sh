#!/usr/bin/env bash
# ===========================================================================
# Set up shared NFS storage so per-user notebook work follows users across
# nodes (fixes node-local volumes in Swarm).
#
#   sudo ./scripts/setup_nfs.sh server --subnet 192.168.1.0/24   # on the master
#   sudo ./scripts/setup_nfs.sh client --server 192.168.1.10     # on each worker
#
# Exports /srv/satyameba (with users/ and shared/ subdirs) from the server and
# mounts it at the SAME path on every client, so the spawner's host bind-mounts
# resolve to the same data everywhere. no_root_squash lets the Hub (root) create
# per-user dirs on the share — keep this on a trusted VLAN only.
# ===========================================================================
set -euo pipefail
ROOT_DIR=/srv/satyameba
NB_UID=1000; NB_GID=100

MODE="${1:-}"; shift || true
SUBNET=""; SERVER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --subnet) SUBNET="$2"; shift ;;
    --server) SERVER="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
say() { printf "\033[1;35m[nfs]\033[0m %s\n" "$*"; }

case "$MODE" in
  server)
    [[ -z "$SUBNET" ]] && { echo "server needs --subnet CIDR (e.g. 192.168.1.0/24)"; exit 1; }
    say "Installing nfs-kernel-server…"
    apt-get update -y && apt-get install -y nfs-kernel-server
    mkdir -p "$ROOT_DIR/users" "$ROOT_DIR/shared"
    chown -R "$NB_UID:$NB_GID" "$ROOT_DIR"
    chmod 2775 "$ROOT_DIR/users" "$ROOT_DIR/shared"
    EXPORT_LINE="$ROOT_DIR ${SUBNET}(rw,sync,no_subtree_check,no_root_squash)"
    if ! grep -qsF "$ROOT_DIR ${SUBNET}" /etc/exports; then
      echo "$EXPORT_LINE" >> /etc/exports
      say "added export: $EXPORT_LINE"
    fi
    exportfs -ra
    systemctl enable --now nfs-kernel-server
    say "Server ready, exporting $ROOT_DIR to $SUBNET"
    ;;
  client)
    [[ -z "$SERVER" ]] && { echo "client needs --server IP"; exit 1; }
    say "Installing nfs-common…"
    apt-get update -y && apt-get install -y nfs-common
    mkdir -p "$ROOT_DIR"
    FSTAB_LINE="${SERVER}:${ROOT_DIR}  ${ROOT_DIR}  nfs  defaults,_netdev,soft,timeo=30  0  0"
    if ! grep -qsF "${SERVER}:${ROOT_DIR}" /etc/fstab; then
      echo "$FSTAB_LINE" >> /etc/fstab
      say "added fstab mount"
    fi
    mount "$ROOT_DIR" 2>/dev/null || mount -t nfs "${SERVER}:${ROOT_DIR}" "$ROOT_DIR"
    say "Mounted ${SERVER}:${ROOT_DIR} at ${ROOT_DIR}"
    ;;
  *)
    echo "usage: $0 {server --subnet CIDR | client --server IP}"; exit 1 ;;
esac
say "Done."
