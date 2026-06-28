#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — all-in-one installer wizard.
#
#   sudo ./setup/install_wizard.sh   [--unattended] [--dry-run] [--verbose]
#
# A single, powerful, installer-style wizard that collects your settings in
# input fields, then runs the whole pipeline IN ORDER with a live progress bar:
#
#     dependencies → NVIDIA driver/toolkit → backend (secrets, scan, build,
#     bring-up) → boot services → optional desktop-slim + console TUI → verify
#     → owner break-glass (ownership / Tailscale / tamper watchdog)
#
# Works on a console or over SSH at any resolution (dialog → whiptail → plain
# prompts). Failsafe: every step is logged, a failure stops with a clear message,
# and the owner break-glass step (which needs an interactive Tailscale login)
# runs last, in the terminal.
#
#   --unattended  use defaults / env vars, no prompts (for automation)
#   --dry-run     show what WOULD run, change nothing
#   --verbose     stream step output to the terminal instead of the progress bar
# ===========================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/lib_pkg.sh"

DRY=0; UNATTENDED=0; VERBOSE=0
for a in "$@"; do case "$a" in
  --unattended) UNATTENDED=1 ;; --dry-run) DRY=1 ;; --verbose) VERBOSE=1 ;;
  -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
esac; done

LOG="${SAT_INSTALL_LOG:-/tmp/satyameba-install.$(date +%s).log}"
: >"$LOG" 2>/dev/null || { LOG="./satyameba-install.log"; : >"$LOG"; }
FAILF="$(mktemp)"; : >"$FAILF"
BT="SATYAMEBA Installer  ·  © Samaraho Mukherjee"

# --- run as root so no sudo prompts interrupt the progress bar --------------
if [[ $EUID -ne 0 && $DRY -eq 0 ]]; then
  echo "Re-running with sudo (needed to install packages and services)…"
  exec sudo -E bash "$0" "$@"
fi

# --- pick a UI: dialog (best) → whiptail → plain prompts --------------------
pkg_detect || true
if ! command -v dialog >/dev/null 2>&1 && ! command -v whiptail >/dev/null 2>&1; then
  [[ $DRY -eq 0 ]] && pkg_install dialog 2>/dev/null || true
fi
UI="none"
command -v whiptail >/dev/null 2>&1 && UI="whiptail"
command -v dialog   >/dev/null 2>&1 && UI="dialog"

ui_input() { # prompt default
  if [[ "$UI" == "none" || $UNATTENDED -eq 1 ]]; then echo "${2:-}"; return; fi
  "$UI" --backtitle "$BT" --inputbox "$1" 10 72 "${2:-}" 3>&1 1>&2 2>&3 || echo "${2:-}"; }
ui_yesno() { # prompt default(0/1)
  if [[ "$UI" == "none" || $UNATTENDED -eq 1 ]]; then [[ "${2:-1}" -eq 1 ]]; return; fi
  "$UI" --backtitle "$BT" --yesno "$1" 11 72; }
ui_menu() { # title then tag desc pairs
  local t="$1"; shift
  if [[ "$UI" == "none" || $UNATTENDED -eq 1 ]]; then echo "$1"; return; fi
  "$UI" --backtitle "$BT" --menu "$t" 16 72 6 "$@" 3>&1 1>&2 2>&3; }
ui_msg() { [[ "$UI" == "none" || $UNATTENDED -eq 1 ]] && { echo "$1"; return; }; "$UI" --backtitle "$BT" --msgbox "$1" 16 74; }

# --- welcome ---------------------------------------------------------------
ui_msg "Welcome to the SATYAMEBA installer.

This will set up your private Jupyter cloud end to end: dependencies, GPU stack,
backend, boot services, and (optionally) the owner break-glass control plane.

You'll answer a few questions, then watch it install. Detailed log:
  $LOG"

# --- collect settings ------------------------------------------------------
DET_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
DET_GPU=0; command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1 && DET_GPU=1

MODE="$(ui_menu "Deployment mode" \
  single "Everything on this one machine" \
  master "Master / control plane (workers join later)")"
MODE="${MODE:-single}"

OWNER_USER="$(ui_input 'Owner username (the un-removable owner account):' "${SAT_OWNER_USER:-samaraho}")"
OWNER_EMAIL="$(ui_input 'Owner email:' "${SAT_OWNER_EMAIL:-owner@satyameba.local}")"
DOMAIN="$(ui_input 'Domain (TLS / dashboard URL):' "${SAT_DOMAIN:-satyameba.local}")"
USERS="$(ui_input 'Expected number of users (sizes the deployment):' "${SAT_USERS:-8}")"
ADV="$DET_IP"
[[ "$MODE" == "master" ]] && ADV="$(ui_input 'Advertise IP other nodes reach this master on:' "$DET_IP")"

GPU=0; ui_yesno "Use an NVIDIA GPU on this machine?$([[ $DET_GPU -eq 1 ]] && echo ' (one was detected)')" "$DET_GPU" && GPU=1
NFS=0; [[ "$MODE" == "master" ]] && { ui_yesno "Share user storage across nodes via NFS (recommended for multi-node)?" 1 && NFS=1; }
DO_SERVICES=0; ui_yesno "Install SATYAMEBA as boot services so it auto-starts on power-on?" 1 && DO_SERVICES=1
DO_DESKTOP=0; ui_yesno "Uninstall the desktop to save RAM + run the neon console dashboard on the monitor? (reversible)" 0 && DO_DESKTOP=1

DO_OWNER=0; SSHKEY=""; GRACE=30; ARM_WIPE=0
if ui_yesno "Set up the OWNER break-glass control plane now (Tailscale tunnel + un-removable owner + tamper watchdog)?" 1; then
  DO_OWNER=1
  SSHKEY="$(ui_input 'Path to your SSH public key (break-glass access):' "${SAT_SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}")"
  GRACE="$(ui_input 'Tamper-watchdog grace window, minutes (before any auto-wipe):' '30')"
  ui_yesno "ARM the irreversible auto crypto-erase on tamper? Choose NO unless you have read owner-setup/README.md and want wipe-on-tamper." 0 && ARM_WIPE=1
fi

# --- confirm ---------------------------------------------------------------
SUMMARY="Review:
  Mode:            $MODE
  Owner:           $OWNER_USER <$OWNER_EMAIL>
  Domain:          $DOMAIN        Users: $USERS
  $( [[ $MODE == master ]] && echo "Advertise IP:    $ADV" )
  GPU:             $([[ $GPU -eq 1 ]] && echo yes || echo no)$( [[ $MODE == master ]] && echo "    NFS: $([[ $NFS -eq 1 ]] && echo yes || echo no)" )
  Boot services:   $([[ $DO_SERVICES -eq 1 ]] && echo yes || echo no)
  Slim desktop:    $([[ $DO_DESKTOP -eq 1 ]] && echo yes || echo no)
  Owner break-glass:$([[ $DO_OWNER -eq 1 ]] && echo " yes (arm-wipe: $([[ $ARM_WIPE -eq 1 ]] && echo ON || echo off))" || echo ' no')

Proceed with the installation?"
if [[ $UNATTENDED -eq 0 ]]; then ui_yesno "$SUMMARY" 1 || { echo "Cancelled."; exit 0; }; fi

# --- build the ordered step list (each = an existing, tested script) -------
S_LABEL=(); S_CMD=()
add() { S_LABEL+=("$1"); S_CMD+=("$2"); }

add "Dependencies (curl, python3, Docker)" \
    "pkg_refresh; pkg_install curl ca-certificates python3; command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh; svc_enable_now docker"
[[ $GPU -eq 1 ]] && add "NVIDIA Container Toolkit + driver check" \
    "bash '$ROOT/scripts/setup_nvidia_toolkit.sh'"
if [[ "$MODE" == "single" ]]; then
  add "Backend: secrets, scan, build images, bring up" \
      "bash '$ROOT/setup/master_init.sh' --single --domain '$DOMAIN' --users '$USERS' $([[ $GPU -eq 1 ]] && echo --gpu)"
  SVCMODE="compose"
else
  add "Backend: secrets, scan, build images, deploy swarm" \
      "bash '$ROOT/setup/master_init.sh' --advertise-addr '$ADV' --domain '$DOMAIN' --users '$USERS' $([[ $GPU -eq 1 ]] && echo --gpu) $([[ $NFS -eq 1 ]] && echo --nfs)"
  SVCMODE="swarm"
fi
[[ $DO_SERVICES -eq 1 ]] && add "Install boot services$([[ $DO_DESKTOP -eq 1 ]] && echo ' + console TUI')" \
    "bash '$ROOT/setup/install_services.sh' --mode $SVCMODE $([[ $DO_DESKTOP -eq 1 ]] && echo --tui)"
[[ $DO_DESKTOP -eq 1 ]] && add "Slim desktop (boot-to-console, reversible)" \
    "bash '$ROOT/setup/uninstall_desktop.sh' --yes"
add "Verify the stack is answering" \
    "for i in 1 2 3 4 5 6 7 8; do curl -fsS -k https://localhost/healthz >/dev/null 2>&1 && exit 0; sleep 5; done; curl -fsS -k https://localhost/healthz >/dev/null 2>&1"

TOTAL=${#S_LABEL[@]}

# --- run the non-interactive pipeline under a live progress bar ------------
run_ui() {
  local i pct
  for i in "${!S_LABEL[@]}"; do
    pct=$(( i * 100 / TOTAL ))
    printf 'XXX\n%d\nStep %d/%d — %s\n(log: %s)\nXXX\n' "$pct" "$((i+1))" "$TOTAL" "${S_LABEL[$i]}" "$LOG"
    if [[ $DRY -eq 1 ]]; then echo "[DRY] ${S_CMD[$i]}" >>"$LOG"; sleep 0.4
    else bash -c "${S_CMD[$i]}" >>"$LOG" 2>&1 || { echo "$i" >"$FAILF"; break; }; fi
  done
  printf 'XXX\n100\nFinishing…\nXXX\n'
}
run_plain() {
  local i
  for i in "${!S_LABEL[@]}"; do
    printf '\033[1;36m── [%d/%d] %s ──\033[0m\n' "$((i+1))" "$TOTAL" "${S_LABEL[$i]}"
    if [[ $DRY -eq 1 ]]; then echo "[DRY] ${S_CMD[$i]}";
    else bash -c "${S_CMD[$i]}" 2>&1 | tee -a "$LOG"; [[ ${PIPESTATUS[0]} -ne 0 ]] && { echo "$i" >"$FAILF"; break; }; fi
  done
}

if [[ "$UI" == "none" || $VERBOSE -eq 1 || $DRY -eq 1 ]]; then run_plain
else run_ui | "$UI" --backtitle "$BT" --title "Installing SATYAMEBA" --gauge "Starting…" 14 78 0; fi

FAILED_IDX="$(cat "$FAILF" 2>/dev/null)"
if [[ -n "$FAILED_IDX" ]]; then
  ui_msg "❌ Installation stopped at step $((FAILED_IDX+1))/$TOTAL:
  ${S_LABEL[$FAILED_IDX]}

Last log lines:
$(tail -n 8 "$LOG")

Full log: $LOG
Fix the issue and re-run — the wizard is idempotent."
  exit 1
fi

# --- owner break-glass: interactive (Tailscale login) at the very end ------
if [[ $DO_OWNER -eq 1 && $DRY -eq 0 ]]; then
  ui_msg "Final step: OWNER break-glass setup.
Tailscale may print a login URL — open it and approve this machine.
Running in the terminal now…"
  clear 2>/dev/null || true
  bash "$ROOT/owner-setup/owner_setup.sh" --role master \
       --owner-username "$OWNER_USER" --owner-email "$OWNER_EMAIL" \
       --ssh-pubkey "$SSHKEY" --grace-mins "$GRACE" \
       $([[ $ARM_WIPE -eq 1 ]] && echo --arm-autowipe) 2>&1 | tee -a "$LOG"
fi

# --- summary ---------------------------------------------------------------
DRIVER_NOTE=""
[[ $GPU -eq 1 ]] && ! { command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; } && \
  DRIVER_NOTE="
  ⚠ Install the NVIDIA driver (RTX 5070 → 555+) and reboot, then: sudo ./scripts/verify_gpu.sh"
WORKER_NOTE=""
[[ "$MODE" == "master" ]] && WORKER_NOTE="
  • Add workers with the join command printed in the log: $LOG
    (same-VLAN → setup/worker_join.sh; remote → setup/remote_node_join.sh)"
GPU_VERIFY=""
[[ $GPU -eq 1 ]] && GPU_VERIFY="
  • Confirm GPU sharing on this hardware: sudo ./scripts/verify_gpu.sh"

ui_msg "✅ SATYAMEBA is installed.

  • Dashboard:  https://${DOMAIN}/   (admin/owner credentials are in $ROOT/.env)
  • Change the owner password on first login.$DRIVER_NOTE$WORKER_NOTE$GPU_VERIFY
  $([[ $DO_DESKTOP -eq 1 ]] && echo '• Reboot to free the desktop RAM; the console dashboard owns tty1.')
  $([[ $DO_OWNER -eq 1 ]] && echo '• Owner break-glass is set — read owner-setup/README.md (the wipe is irreversible).')

Full install log: $LOG"
clear 2>/dev/null || true
echo "SATYAMEBA install complete. Dashboard: https://${DOMAIN}/  ·  log: $LOG"
rm -f "$FAILF"
