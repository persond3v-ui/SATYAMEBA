#!/usr/bin/env bash
# ===========================================================================
# Undo uninstall_desktop.sh — restore the desktop environment.
#
#   sudo ./setup/reinstall_desktop.sh [--yes]
#
# Reads /etc/satyameba/desktop.state to know what was changed, reinstalls the DE
# meta-package if it was purged, restores the graphical boot target, and frees
# tty1 again. Multi-distro.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib_pkg.sh"
ASSUME_YES=0; [[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && ASSUME_YES=1
say() { printf "\033[1;34m[desktop]\033[0m %s\n" "$*"; }

pkg_detect
DE=""; PURGED=0; PREV_TARGET="graphical.target"
[[ -f /etc/satyameba/desktop.state ]] && source /etc/satyameba/desktop.state || true

# Stop owning tty1.
if command -v systemctl >/dev/null 2>&1; then
  _sudo systemctl disable --now satyameba-tui 2>/dev/null || true
fi

if [[ "${PURGED:-0}" -eq 1 && -n "${DE:-}" ]]; then
  say "Reinstalling the ${DE} desktop (this can take a while)…"
  pkg_refresh
  case "${DE}:${PKG_OS}" in
    gnome:debian) pkg_install gnome-shell gnome-session ;;
    gnome:arch)   pkg_install gnome ;;
    kde:debian)   pkg_install kde-plasma-desktop ;;
    kde:arch)     pkg_install plasma ;;
    xfce:debian)  pkg_install xfce4 ;;
    xfce:arch)    pkg_install xfce4 ;;
    *) say "Install your DE meta-package manually for ${DE} on ${PKG_OS}." ;;
  esac
fi

if command -v systemctl >/dev/null 2>&1; then
  say "Restoring graphical boot target (${PREV_TARGET:-graphical.target})…"
  _sudo systemctl set-default "${PREV_TARGET:-graphical.target}"
fi
say "Done. Reboot to return to the desktop."
