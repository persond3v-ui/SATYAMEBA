#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — enable per-user at-rest encryption (gocryptfs).
#
#   sudo ./setup/gocryptfs_setup.sh
#
# Installs gocryptfs (any distro), allows FUSE mounts to be shared into the
# notebook containers, provisions the owner root KEK, creates the cipher/plain
# bases, and installs + starts the mount agent as a boot service. After this,
# set SAT_USER_ENCRYPTION=gocryptfs (and SAT_USER_STORAGE_MODE=host) in .env and
# redeploy so notebooks bind-mount the decrypted view.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib_pkg.sh"
say() { printf "\033[1;35m[encrypt]\033[0m %s\n" "$*"; }
pkg_detect || true

KEYSTORE="${SAT_KEYSTORE:-/srv/satyameba/keystore}"
DATAROOT="${SAT_DATAROOT:-/srv/satyameba}"
CIPHER_BASE="${SAT_CIPHER_BASE:-$DATAROOT/cipher}"
PLAIN_BASE="${SAT_PLAIN_BASE:-$DATAROOT/plain}"

# 1) Install gocryptfs (repo package, else the upstream static binary).
if ! command -v gocryptfs >/dev/null 2>&1; then
  say "Installing gocryptfs…"
  pkg_refresh || true
  pkg_install gocryptfs fuse || true
fi
if ! command -v gocryptfs >/dev/null 2>&1; then
  say "Package not available; fetching the upstream static binary…"
  ver="v2.4.0"
  url="https://github.com/rfjakob/gocryptfs/releases/download/${ver}/gocryptfs_${ver}_linux-static_amd64.tar.gz"
  tmp="$(mktemp -d)"
  curl -fsSL "$url" | tar -xz -C "$tmp" && install -m 0755 "$tmp/gocryptfs" /usr/local/bin/gocryptfs
  rm -rf "$tmp"
fi
command -v gocryptfs >/dev/null 2>&1 || { echo "gocryptfs install failed"; exit 1; }
say "gocryptfs: $(gocryptfs --version 2>&1 | head -n1)"

# 2) Allow the FUSE mount to be visible to the notebook container's UID.
if [[ -f /etc/fuse.conf ]] && ! grep -q '^user_allow_other' /etc/fuse.conf; then
  echo "user_allow_other" >> /etc/fuse.conf
  say "enabled user_allow_other in /etc/fuse.conf"
fi

# 3) Provision the owner root KEK (idempotent) + base dirs.
mkdir -p "$KEYSTORE"; chmod 700 "$KEYSTORE"
if [[ ! -f "$KEYSTORE/kek.key" ]]; then
  head -c 32 /dev/urandom > "$KEYSTORE/kek.key"; chmod 600 "$KEYSTORE/kek.key"
  say "generated root KEK at $KEYSTORE/kek.key (back this up offline — losing it = losing the data)"
else
  say "root KEK already present"
fi
mkdir -p "$CIPHER_BASE" "$PLAIN_BASE"; chmod 700 "$CIPHER_BASE" "$PLAIN_BASE"

# 4) Install + start the mount agent as a boot service.
if command -v systemctl >/dev/null 2>&1; then
  sed "s|__ROOT__|$ROOT|g" "$ROOT/setup/systemd/satyameba-cryptagent.service" \
    > /etc/systemd/system/satyameba-cryptagent.service
  systemctl daemon-reload
  systemctl enable --now satyameba-cryptagent.service 2>/dev/null || true
  say "cryptagent service installed + started"
else
  say "no systemd — run setup/satyameba-cryptagent.sh yourself (or at boot)"
fi

say "Done. Now set in .env:  SAT_USER_ENCRYPTION=gocryptfs  and  SAT_USER_STORAGE_MODE=host"
say "then redeploy. New + existing notebooks will bind-mount the decrypted view;"
say "the disk only ever holds ciphertext. The owner crypto-erase wipes it instantly."
