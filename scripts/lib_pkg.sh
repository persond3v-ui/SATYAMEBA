#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — portable package-manager abstraction.
#
# Source this from any setup script to install packages on ANY mainstream Linux
# distro regardless of version: Debian/Ubuntu (apt), Fedora/RHEL/Rocky/Alma
# (dnf/yum), Arch (pacman), openSUSE (zypper), Alpine (apk).
#
#   source "$(dirname "$0")/../scripts/lib_pkg.sh"
#   pkg_detect; pkg_refresh
#   pkg_install curl ca-certificates
#   ensure_cmd python3 python3
#
# Package *names* differ across distros, so pkg_install maps a small set of
# common logical names (curl, python3, python3-tk, jq, …) to each family.
# ===========================================================================

PKG=""          # apt | dnf | yum | pacman | zypper | apk
PKG_OS=""       # debian | fedora | rhel | arch | suse | alpine | unknown

pkg_detect() {
  if [[ -r /etc/os-release ]]; then . /etc/os-release; fi
  if   command -v apt-get >/dev/null 2>&1; then PKG="apt"
  elif command -v dnf     >/dev/null 2>&1; then PKG="dnf"
  elif command -v yum     >/dev/null 2>&1; then PKG="yum"
  elif command -v pacman  >/dev/null 2>&1; then PKG="pacman"
  elif command -v zypper  >/dev/null 2>&1; then PKG="zypper"
  elif command -v apk     >/dev/null 2>&1; then PKG="apk"
  else PKG=""; fi
  case " ${ID:-} ${ID_LIKE:-} " in
    *debian*|*ubuntu*) PKG_OS="debian" ;;
    *fedora*)          PKG_OS="fedora" ;;
    *rhel*|*centos*|*rocky*|*alma*) PKG_OS="rhel" ;;
    *arch*)            PKG_OS="arch" ;;
    *suse*)            PKG_OS="suse" ;;
    *alpine*)          PKG_OS="alpine" ;;
    *) PKG_OS="unknown" ;;
  esac
  [[ -n "$PKG" ]] || { echo "[pkg] no supported package manager found"; return 1; }
  echo "[pkg] distro=${PRETTY_NAME:-$PKG_OS} manager=$PKG"
}

_sudo() { if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi; }

pkg_refresh() {
  [[ -n "$PKG" ]] || pkg_detect
  case "$PKG" in
    apt)    _sudo apt-get update -y ;;
    dnf)    _sudo dnf -y makecache || true ;;
    yum)    _sudo yum -y makecache || true ;;
    pacman) _sudo pacman -Sy --noconfirm ;;
    zypper) _sudo zypper --non-interactive refresh ;;
    apk)    _sudo apk update ;;
  esac
}

# Map a logical package name to the per-distro real name.
_pkg_map() {
  local name="$1"
  case "$name:$PKG" in
    python3-tk:apt)    echo "python3-tk" ;;
    python3-tk:dnf|python3-tk:yum) echo "python3-tkinter" ;;
    python3-tk:pacman) echo "tk" ;;
    python3-tk:zypper) echo "python3-tk" ;;
    python3-tk:apk)    echo "python3-tkinter" ;;
    python3-curses:apk) echo "" ;;             # curses is in stdlib everywhere
    dialog:*)          echo "dialog" ;;
    whiptail:apt)      echo "whiptail" ;;
    whiptail:dnf|whiptail:yum) echo "newt" ;;
    whiptail:zypper)   echo "newt" ;;
    whiptail:pacman)   echo "libnewt" ;;
    whiptail:apk)      echo "newt" ;;
    ca-certificates:*) echo "ca-certificates" ;;
    *) echo "$name" ;;
  esac
}

pkg_install() {
  [[ -n "$PKG" ]] || pkg_detect
  local mapped=() p
  for p in "$@"; do p="$(_pkg_map "$p")"; [[ -n "$p" ]] && mapped+=("$p"); done
  [[ ${#mapped[@]} -eq 0 ]] && return 0
  echo "[pkg] installing: ${mapped[*]}"
  case "$PKG" in
    apt)    _sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${mapped[@]}" ;;
    dnf)    _sudo dnf install -y "${mapped[@]}" ;;
    yum)    _sudo yum install -y "${mapped[@]}" ;;
    pacman) _sudo pacman -S --noconfirm --needed "${mapped[@]}" ;;
    zypper) _sudo zypper --non-interactive install -y "${mapped[@]}" ;;
    apk)    _sudo apk add "${mapped[@]}" ;;
  esac
}

# Install the package that provides <cmd>, only if <cmd> is missing.
ensure_cmd() {
  local cmd="$1"; shift
  command -v "$cmd" >/dev/null 2>&1 && return 0
  pkg_install "${@:-$cmd}"
}

# Best-effort: ensure a service is enabled + started at boot (systemd or OpenRC).
svc_enable_now() {
  local svc="$1"
  if command -v systemctl >/dev/null 2>&1; then
    _sudo systemctl enable --now "$svc" 2>/dev/null || true
  elif command -v rc-update >/dev/null 2>&1; then
    _sudo rc-update add "$svc" default 2>/dev/null || true
    _sudo rc-service "$svc" start 2>/dev/null || true
  fi
}
