#!/usr/bin/env bash
# ===========================================================================
# Install SATYAMEBA as boot-time systemd services so the whole platform comes
# up on power-on with no human in the loop (failproof, plug-n-play).
#
#   sudo ./setup/install_services.sh [--mode compose|swarm] [--tui]
#
#   --mode  compose (single host, default) or swarm (multi-node manager).
#   --tui   also install the tty1 console dashboard service (for headless nodes
#           with the desktop removed).
#
# Idempotent. Works wherever systemd is present (most distros). On OpenRC-only
# systems (e.g. Alpine) it prints the equivalent manual step.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="compose"; TUI=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) MODE="$2"; shift ;;
    --tui)  TUI=1 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
say() { printf "\033[1;35m[services]\033[0m %s\n" "$*"; }

if ! command -v systemctl >/dev/null 2>&1; then
  say "systemd not found. On OpenRC, add an init script that runs:"
  say "  (cd $ROOT && docker compose up -d)   # or your swarm deploy"
  exit 0
fi

DOCKER="$(command -v docker || echo /usr/bin/docker)"
if [[ "$MODE" == "swarm" ]]; then
  START="/bin/bash -c 'source $ROOT/scripts/load_env.sh; load_env $ROOT/.env; $DOCKER stack deploy -c $ROOT/docker-compose.swarm.yml satyameba'"
  STOP="$DOCKER stack rm satyameba"
else
  START="$DOCKER compose -f $ROOT/docker-compose.yml up -d"
  STOP="$DOCKER compose -f $ROOT/docker-compose.yml down"
fi

gen() {  # gen <template> <dest>
  sed -e "s|__ROOT__|$ROOT|g" \
      -e "s|__START__|$START|g" \
      -e "s|__STOP__|$STOP|g" "$1" | tee "$2" >/dev/null
}

say "Installing satyameba.service (mode=$MODE)…"
gen "$ROOT/setup/systemd/satyameba.service" /etc/systemd/system/satyameba.service
systemctl daemon-reload
systemctl enable satyameba.service
say "Enabled. Start now with: sudo systemctl start satyameba"

say "Installing the periodic cleanup timer (reclaims disk every 6h)…"
gen "$ROOT/setup/systemd/satyameba-cleanup.service" /etc/systemd/system/satyameba-cleanup.service
gen "$ROOT/setup/systemd/satyameba-cleanup.timer"   /etc/systemd/system/satyameba-cleanup.timer
systemctl daemon-reload
systemctl enable --now satyameba-cleanup.timer 2>/dev/null || true

if [[ "$TUI" -eq 1 ]]; then
  say "Installing satyameba-tui.service on tty1…"
  gen "$ROOT/setup/systemd/satyameba-tui.service" /etc/systemd/system/satyameba-tui.service
  systemctl daemon-reload
  systemctl enable satyameba-tui.service
  say "The console dashboard will own tty1 on next boot (start now: systemctl start satyameba-tui)."
fi
say "Done. The platform will now start automatically at boot."
