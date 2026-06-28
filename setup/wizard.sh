#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — one-button setup wizard (TUI).
#
#   sudo ./setup/wizard.sh
#
# A whiptail/dialog wizard that runs on a console or over SSH at ANY resolution
# (falls back to plain prompts if whiptail isn't available). It does, step by
# step and failsafe, everything the project promises:
#   deps → Docker → secrets → resource scan → bring the stack up → (optional)
#   GPU, multi-node, boot services, desktop-uninstall, console dashboard.
#
# Designed so a single run on a fresh machine gets SATYAMEBA up and running.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/lib_pkg.sh"
pkg_detect || true

# --- UI helpers: whiptail if present, else dialog, else plain read ----------
ensure_cmd whiptail whiptail 2>/dev/null || true
UI=""
command -v whiptail >/dev/null 2>&1 && UI="whiptail"
[[ -z "$UI" ]] && command -v dialog >/dev/null 2>&1 && UI="dialog"

msg()  { if [[ -n "$UI" ]]; then "$UI" --title "SATYAMEBA" --msgbox "$1" 12 70; else echo; echo "== $1"; read -r -p "[enter] " _; fi; }
ask()  { # ask <prompt> <default>
  if [[ -n "$UI" ]]; then "$UI" --title "SATYAMEBA" --inputbox "$1" 10 70 "${2:-}" 3>&1 1>&2 2>&3
  else read -r -p "$1 [${2:-}]: " a; echo "${a:-${2:-}}"; fi; }
yesno() { if [[ -n "$UI" ]]; then "$UI" --title "SATYAMEBA" --yesno "$1" 10 70; else read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy]$ ]]; fi; }
menu() { # menu <prompt> tag1 desc1 tag2 desc2 ...
  local p="$1"; shift
  if [[ -n "$UI" ]]; then "$UI" --title "SATYAMEBA setup" --menu "$p" 20 74 10 "$@" 3>&1 1>&2 2>&3
  else echo "$p"; local i=1; while [[ $# -gt 0 ]]; do echo "  $1) $2"; shift 2; done; read -r -p "choice: " a; echo "$a"; fi; }
say() { printf "\033[1;33m[wizard]\033[0m %s\n" "$*"; }

[[ $EUID -ne 0 ]] && say "Tip: run with sudo so dependency installs don't prompt repeatedly."

# --- Step 1: dependencies ---------------------------------------------------
install_deps() {
  say "Checking dependencies…"
  pkg_refresh || true
  pkg_install curl ca-certificates python3 || true
  if ! command -v docker >/dev/null 2>&1; then
    if yesno "Docker is not installed. Install Docker Engine now?"; then
      curl -fsSL https://get.docker.com | sh || pkg_install docker || pkg_install docker.io || true
      svc_enable_now docker
    fi
  fi
  command -v docker >/dev/null 2>&1 && say "Docker present: $(docker --version 2>/dev/null)"
}

bring_up_single() {
  local gpu=0
  yesno "Does THIS machine have an NVIDIA GPU to use?" && gpu=1
  say "Bootstrapping single-host deployment…"
  if [[ $gpu -eq 1 ]]; then ./setup/master_init.sh --single --gpu; else ./setup/master_init.sh --single; fi
  if yesno "Install SATYAMEBA as a boot service so it auto-starts on power-on?"; then
    ./setup/install_services.sh --mode compose
    systemctl start satyameba 2>/dev/null || true
  fi
  msg "Single-host SATYAMEBA is up. Open https://localhost/ — admin credentials are in $ROOT/.env"
}

bring_up_master() {
  local adv gpuflag="" nfsflag=""
  adv="$(ask 'VLAN IP other nodes use to reach this master:' "$(hostname -I 2>/dev/null | awk '{print $1}')")"
  yesno "Does this master have an NVIDIA GPU?" && gpuflag="--gpu"
  yesno "Share user storage across nodes via NFS (recommended for multi-node)?" && nfsflag="--nfs"
  ./setup/master_init.sh --advertise-addr "$adv" $gpuflag $nfsflag
  if yesno "Install SATYAMEBA as a boot service (Swarm) so it auto-starts?"; then
    ./setup/install_services.sh --mode swarm
  fi
  msg "Master is up. The exact worker join command was printed above — run it on each worker."
}

join_worker() {
  local mip tok sec gpuflag=""
  mip="$(ask 'Master VLAN IP:' '')"
  tok="$(ask 'Swarm join-token (SWMTKN-...):' '')"
  sec="$(ask 'Node secret (from the master output):' '')"
  yesno "Does this worker have an NVIDIA GPU?" && gpuflag="--gpu"
  ./setup/worker_join.sh --master-ip "$mip" --join-token "$tok" --node-secret "$sec" \
     --gateway "https://$mip" $gpuflag
  msg "Worker joined. It now appears under Admin → Nodes."
}

join_remote() {
  local tsip tok sec gpuflag="" coflag="" key
  msg "Remote join uses Tailscale (separate from same-VLAN join, to avoid confusion)."
  tsip="$(ask "Master's Tailscale IP (100.x.y.z):" '')"
  tok="$(ask 'Swarm join-token (SWMTKN-...):' '')"
  sec="$(ask 'Node secret:' '')"
  key="$(ask 'Tailscale auth key (blank = interactive login):' '')"
  yesno "Does this remote node have an NVIDIA GPU?" && gpuflag="--gpu"
  yesno "Treat as COMPUTE-ONLY (keep no persistent user data here)?" && coflag="--compute-only"
  ./setup/remote_node_join.sh --master-ts-ip "$tsip" --join-token "$tok" --node-secret "$sec" \
     ${key:+--authkey "$key"} $gpuflag $coflag
  msg "Remote node joined over Tailscale."
}

slim_desktop() {
  if yesno "Remove the desktop interface to save RAM (reversible)? A console dashboard takes over the monitor."; then
    local purge=""
    yesno "Also PURGE the desktop packages (bigger win, harder to undo)?" && purge="--purge"
    ./setup/uninstall_desktop.sh $purge --yes
    msg "Desktop slimmed. Reboot to free its RAM. Undo: sudo ./setup/reinstall_desktop.sh"
  fi
}

# --- main menu --------------------------------------------------------------
install_deps
while true; do
  CHOICE="$(menu 'What do you want to set up?' \
    single  'Single host (everything on this machine)' \
    master  'Master / control plane (multi-node lab)' \
    worker  'Worker on the SAME VLAN' \
    remote  'Remote worker (off-VLAN, via Tailscale)' \
    desktop 'Uninstall desktop / console dashboard' \
    quit    'Exit')" || break
  case "$CHOICE" in
    single)  bring_up_single ;;
    master)  bring_up_master ;;
    worker)  join_worker ;;
    remote)  join_remote ;;
    desktop) slim_desktop ;;
    quit|"") break ;;
  esac
done
say "Wizard finished."
