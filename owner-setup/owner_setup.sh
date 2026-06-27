#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — OWNER SETUP (run once per machine, as root).      Owner: Samaraho Mukherjee
#
# Installs and guides you through Tailscale (outbound-only, no router config),
# drops your break-glass SSH key, ensures the un-removable Owner account, and
# installs the tamper watchdog (seal -> grace -> crypto-erase).
#
#   sudo ./owner-setup/owner_setup.sh --role master \
#        --owner-username samaraho --owner-email you@example.com \
#        --ssh-pubkey ~/.ssh/id_ed25519.pub \
#        [--arm-autowipe] [--grace-mins 30] [--alert-cmd 'curl -s https://hook...']
#
#   sudo ./owner-setup/owner_setup.sh --role worker --ssh-pubkey ~/.ssh/id_ed25519.pub
#
# Re-runnable. Read owner-setup/README.md first — the wipe is IRREVERSIBLE.
# ===========================================================================
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
source "$HERE/lib_crypto.sh"

ROLE="master"; OWNER_USER=""; OWNER_EMAIL=""; SSH_PUBKEY=""; ARM=0; GRACE=30; ALERTC=""; TSHOST=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --role) ROLE="$2"; shift ;;
    --owner-username) OWNER_USER="$2"; shift ;;
    --owner-email) OWNER_EMAIL="$2"; shift ;;
    --ssh-pubkey) SSH_PUBKEY="$2"; shift ;;
    --arm-autowipe) ARM=1 ;;
    --grace-mins) GRACE="$2"; shift ;;
    --alert-cmd) ALERTC="$2"; shift ;;
    --tailnet-hostname) TSHOST="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
[[ $EUID -eq 0 ]] || { echo "Run as root (sudo)."; exit 1; }
TSHOST="${TSHOST:-satyameba-$ROLE-$(hostname -s)}"
say() { printf "\033[1;33m[owner-setup]\033[0m %s\n" "$*"; }

# 1) Tailscale -------------------------------------------------------------
if ! command -v tailscale >/dev/null 2>&1; then
  say "Installing Tailscale…"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
say "Bringing Tailscale up (SSH enabled). A sign-in URL will appear — open it in"
say "your browser and authenticate with YOUR account; that ties this node to your"
say "tailnet. Only your identity will be able to reach it (set an ACL in the admin)."
tailscale up --ssh --hostname "$TSHOST" || say "tailscale up returned non-zero (already up?)"
tailscale status || true

# 2) Break-glass SSH key ---------------------------------------------------
if [[ -n "$SSH_PUBKEY" ]]; then
  KEY="$( [[ -f "$SSH_PUBKEY" ]] && cat "$SSH_PUBKEY" || echo "$SSH_PUBKEY" )"
  install -d -m 700 /root/.ssh
  touch /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys
  grep -qF "$KEY" /root/.ssh/authorized_keys || echo "$KEY" >> /root/.ssh/authorized_keys
  say "Owner SSH key added to root authorized_keys (break-glass)."
fi

if [[ "$ROLE" != "master" ]]; then
  say "Worker owner-setup done. (Watchdog + Owner account live on the master.)"
  exit 0
fi

# --- MASTER-only below ----------------------------------------------------
# 3) Ensure the Owner account ---------------------------------------------
cd "$REPO"
if [[ -f .env ]]; then set -a; source .env; set +a; fi
if [[ -n "$OWNER_USER" ]]; then
  # New deploys seed the owner from these; existing deploys are promoted below.
  sed -i "s/^SAT_BOOTSTRAP_ADMIN_USERNAME=.*/SAT_BOOTSTRAP_ADMIN_USERNAME=${OWNER_USER}/" .env 2>/dev/null || true
  [[ -n "$OWNER_EMAIL" ]] && sed -i "s/^SAT_BOOTSTRAP_ADMIN_EMAIL=.*/SAT_BOOTSTRAP_ADMIN_EMAIL=${OWNER_EMAIL}/" .env 2>/dev/null || true
  CID="$(docker ps --format '{{.ID}} {{.Image}}' | awk '/postgres/ {print $1; exit}')"
  if [[ -n "$CID" ]]; then
    docker exec "$CID" psql -U "${POSTGRES_USER:-satyameba}" -d "${POSTGRES_DB:-satyameba}" \
      -c "UPDATE users SET role='owner' WHERE username='${OWNER_USER}';" \
      && say "Promoted '${OWNER_USER}' to OWNER (un-removable)." \
      || say "Could not promote now (will be seeded as owner on next gateway start)."
  fi
fi

# 4) Keystore (anchors at-rest encryption / crypto-erase) ------------------
keystore_init

# 5) Watchdog config + systemd timer --------------------------------------
install -d -m 700 /etc/satyameba
cat >/etc/satyameba/owner.conf <<EOF
# SATYAMEBA owner watchdog config
OWNER_USERNAME="${OWNER_USER:-}"
ARM_AUTOWIPE="${ARM}"
GRACE_MINS="${GRACE}"
ALERT_CMD='${ALERTC}'
POSTGRES_USER="${POSTGRES_USER:-satyameba}"
POSTGRES_DB="${POSTGRES_DB:-satyameba}"
EOF
chmod 600 /etc/satyameba/owner.conf

cat >/etc/systemd/system/satyameba-watchdog.service <<EOF
[Unit]
Description=SATYAMEBA tamper watchdog (owner)
[Service]
Type=oneshot
ExecStart=${HERE}/watchdog.sh
EOF
cat >/etc/systemd/system/satyameba-watchdog.timer <<EOF
[Unit]
Description=SATYAMEBA tamper watchdog timer
[Timer]
OnBootSec=2min
OnUnitActiveSec=2min
[Install]
WantedBy=timers.target
EOF
chmod +x "$HERE/watchdog.sh"
systemctl daemon-reload
systemctl enable --now satyameba-watchdog.timer

cat <<BANNER

============================================================================
 OWNER SETUP COMPLETE (master)
   Tailnet host : ${TSHOST}   (SSH over the tunnel from anywhere)
   Owner account: ${OWNER_USER:-<seeded on next gateway start>}  (un-removable)
   Watchdog     : every 2 min · auto-wipe ARMED=${ARM} · grace=${GRACE}m
   Keystore     : ${KEYSTORE}

 IMPORTANT
  - Set a Tailscale ACL so ONLY your identity can SSH these nodes.
  - If auto-wipe is armed, tampering with the Owner account or Tailscale will,
    after the grace window, IRREVERSIBLY crypto-erase ALL data. Tell your
    students (consent). Owner-triggered wipe: owner-setup/panic.sh.
  - Pair with owner-setup/harden_host.sh + LUKS/BIOS lock for physical security.
============================================================================
BANNER
