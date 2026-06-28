#!/usr/bin/env bash
# ===========================================================================
# Free the RAM a desktop environment eats on a compute node — reversibly.
#
#   sudo ./setup/uninstall_desktop.sh [--purge] [--yes]
#
# Default (SAFE, instantly reversible): switch the boot target to multi-user
# (console only). The DE's processes never start, so its RAM is freed at boot,
# and the curses console dashboard takes over tty1. Undo with reinstall_desktop.sh.
#
#   --purge   Actually remove the detected desktop packages (autodetected DE,
#             multi-distro). Bigger RAM/disk win, but heavier to undo. Guarded.
#   --yes     Non-interactive (assume yes) — for the one-button wizard.
#
# Autodetects GNOME / KDE / XFCE / etc.; never assumes Debian/GNOME.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib_pkg.sh"
PURGE=0; ASSUME_YES=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --purge) PURGE=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
say() { printf "\033[1;34m[desktop]\033[0m %s\n" "$*"; }
confirm() { [[ "$ASSUME_YES" -eq 1 ]] && return 0; read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy]$ ]]; }

pkg_detect

# --- detect the installed desktop environment ------------------------------
detect_de() {
  local de=""
  command -v gnome-session    >/dev/null 2>&1 && de="gnome"
  command -v startplasma-x11  >/dev/null 2>&1 && de="kde"
  command -v startplasma-wayland >/dev/null 2>&1 && de="kde"
  command -v xfce4-session    >/dev/null 2>&1 && de="xfce"
  command -v cinnamon-session >/dev/null 2>&1 && de="cinnamon"
  command -v mate-session     >/dev/null 2>&1 && de="mate"
  command -v lxsession        >/dev/null 2>&1 && de="lxde"
  echo "$de"
}
DE="$(detect_de)"
say "Detected desktop: ${DE:-none}   (boot target now: $(systemctl get-default 2>/dev/null || echo n/a))"

# Record what we did so reinstall_desktop.sh can undo it precisely.
mkdir -p /etc/satyameba
echo "DE=${DE}"        >  /etc/satyameba/desktop.state
echo "PURGED=${PURGE}" >> /etc/satyameba/desktop.state
echo "PREV_TARGET=$(systemctl get-default 2>/dev/null || echo graphical.target)" >> /etc/satyameba/desktop.state

# --- always: boot to console (instant, reversible RAM win) -----------------
if command -v systemctl >/dev/null 2>&1; then
  say "Setting boot target to multi-user (console)…"
  _sudo systemctl set-default multi-user.target
  # Stop a running graphical session now (best-effort).
  _sudo systemctl isolate multi-user.target 2>/dev/null || true
fi

# --- optional: actually remove the DE packages -----------------------------
if [[ "$PURGE" -eq 1 && -n "$DE" ]]; then
  declare -A META=(
    [gnome:debian]="gnome-shell gnome-session ubuntu-desktop gnome-core"
    [gnome:fedora]="@gnome-desktop"
    [gnome:rhel]="@gnome-desktop"
    [gnome:arch]="gnome"
    [gnome:suse]="patterns-gnome-gnome"
    [kde:debian]="kde-plasma-desktop plasma-desktop"
    [kde:fedora]="@kde-desktop"
    [kde:arch]="plasma"
    [xfce:debian]="xfce4"
    [xfce:fedora]="@xfce-desktop"
    [xfce:arch]="xfce4"
  )
  pkgs="${META[${DE}:${PKG_OS}]:-}"
  if [[ -z "$pkgs" ]]; then
    say "No purge mapping for ${DE} on ${PKG_OS}; left packages in place (boot-to-console still applied)."
  elif confirm "Remove desktop packages: $pkgs ? This is harder to undo."; then
    say "Removing $pkgs …"
    case "$PKG" in
      apt)    _sudo env DEBIAN_FRONTEND=noninteractive apt-get purge -y $pkgs || true
              _sudo apt-get autoremove -y || true ;;
      dnf)    _sudo dnf group remove -y "${pkgs#@}" 2>/dev/null || _sudo dnf remove -y $pkgs || true ;;
      yum)    _sudo yum groupremove -y "${pkgs#@}" 2>/dev/null || _sudo yum remove -y $pkgs || true ;;
      pacman) _sudo pacman -Rns --noconfirm $pkgs || true ;;
      zypper) _sudo zypper --non-interactive remove -y $pkgs || true ;;
    esac
  fi
fi

# --- bring up the console dashboard on tty1 --------------------------------
if [[ -f "$ROOT/setup/install_services.sh" ]]; then
  say "Installing the console dashboard on tty1…"
  _sudo bash "$ROOT/setup/install_services.sh" --tui || true
  _sudo systemctl start satyameba-tui 2>/dev/null || true
fi

say "Done. This node now boots to the console + SATYAMEBA dashboard."
say "Undo any time with:  sudo ./setup/reinstall_desktop.sh"
