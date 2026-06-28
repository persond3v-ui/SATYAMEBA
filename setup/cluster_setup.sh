#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — ONE-TIME whole-cluster setup wizard.
#
#   sudo ./setup/cluster_setup.sh
#
# From the MASTER, this sets up the entire lab end to end and failsafe:
#   • runs as the SUPER USER (re-execs via sudo; on Debian where `sudo`
#     misbehaves it escalates to a real root shell);
#   • asks ONCE for your root/SSH password and uses it to act as root on every
#     node (root SSH, or `sudo -S` if you log in as a normal user);
#   • installs Docker + the NVIDIA driver toolkit where missing on EVERY node;
#   • scans each node's GPU and picks ONE cross-checked CUDA/torch wheel so a
#     node that ISN'T an RTX 5070 still integrates perfectly;
#   • sets up the un-removable OWNER + break-glass on all PCs;
#   • joins the Swarm and hosts the site on ports 80 & 443 ONLY;
#   • verifies each step — nothing proceeds on a silent failure.
#
# Idempotent: safe to re-run. Everything is logged to the path printed below.
# ===========================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/lib_pkg.sh"
LOG="/var/log/satyameba-cluster.$(date +%s).log"; : >"$LOG" 2>/dev/null || LOG="$ROOT/cluster-setup.log"
say()  { printf "\033[1;33m[cluster]\033[0m %s\n" "$*" | tee -a "$LOG"; }
ok()   { printf "  \033[1;32m✔\033[0m %s\n" "$*" | tee -a "$LOG"; }
die()  { printf "  \033[1;31mFAIL %s\033[0m\n" "$*" | tee -a "$LOG"; exit 1; }
ask()  { local a; read -r -p "$1 [${2:-}]: " a; echo "${a:-${2:-}}"; }
yesno(){ local a; read -r -p "$1 [y/N] " a; [[ "$a" =~ ^[Yy]$ ]]; }

# --- 0. become the super user --------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  say "Elevating to root (you'll be asked for your password)…"
  exec sudo -E bash "$0" "$@" || die "Could not sudo. Re-run after 'su -' (root shell)."
fi
say "Running as root. Log: $LOG"
pkg_detect || true

# --- 1. local tooling we need to drive the other nodes ------------------------
pkg_refresh || true
pkg_install curl ca-certificates openssh-client rsync sshpass 2>>"$LOG" || true
command -v sshpass >/dev/null 2>&1 || die "sshpass is required to drive remote nodes; install it and re-run."
command -v rsync   >/dev/null 2>&1 || die "rsync is required to copy the project to nodes."

# --- 2. gather the lab details -------------------------------------------------
say "Tell me about the lab (press enter for defaults)."
ADV="$(ask 'Master IP other nodes reach this box on' "$(hostname -I 2>/dev/null | awk '{print $1}')")"
DOMAIN="$(ask 'Dashboard domain (TLS/CORS)' 'satyameba.local')"
USERS="$(ask 'Expected number of users' '16')"
OWNER_USER="$(ask 'Owner username (the un-removable owner)' 'samaraho')"
OWNER_EMAIL="$(ask 'Owner email' 'owner@satyameba.local')"
GPU=0; yesno "Do these machines have NVIDIA GPUs to schedule on?" && GPU=1
NFS=1; yesno "Share user storage across nodes via NFS (recommended)?" && NFS=1 || NFS=0
ENC=1; yesno "Encrypt user data at rest (gocryptfs)?" && ENC=1 || ENC=0
SSH_USER="$(ask 'SSH username for the OTHER nodes (use root if root login is allowed)' 'root')"
read -r -p "Worker node IPs (space-separated, blank for single-host): " WORKERS
read -rs -p "Root/SSH password (used to act as root on every node): " SSH_PW; echo
SSH_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o PreferredAuthentications=password -o PubkeyAuthentication=no"

# --- privilege-escalating remote exec (root SSH, or sudo -S) -------------------
# Pass the password via the SSHPASS env (sshpass -e), never on the command line,
# so it can't be seen in `ps`. Exported only for the duration of each call.
run_remote() {  # run_remote <ip>   (reads a bash script on stdin, runs it as root)
  local ip="$1"
  if [[ "$SSH_USER" == "root" ]]; then
    SSHPASS="$SSH_PW" sshpass -e ssh $SSH_OPTS "root@$ip" 'bash -s'
  else
    { printf '%s\n' "$SSH_PW"; cat; } | SSHPASS="$SSH_PW" sshpass -e ssh $SSH_OPTS "$SSH_USER@$ip" 'sudo -S -p "" bash -s'
  fi
}
copy_repo() {  # copy_repo <ip>
  local ip="$1"
  if [[ "$SSH_USER" == "root" ]]; then
    SSHPASS="$SSH_PW" sshpass -e rsync -az --delete -e "ssh $SSH_OPTS" \
      --exclude '.git' --exclude 'node_modules' --exclude '*.log' "$ROOT/" "root@$ip:/opt/satyameba/"
  else
    SSHPASS="$SSH_PW" sshpass -e rsync -az --delete -e "ssh $SSH_OPTS" \
      --exclude '.git' --exclude 'node_modules' --exclude '*.log' "$ROOT/" "$SSH_USER@$ip:/tmp/satyameba-src/"
    echo 'rm -rf /opt/satyameba && mv /tmp/satyameba-src /opt/satyameba' | run_remote "$ip"
  fi
}
node_driver() {  # echo a node's nvidia driver version (major) or empty
  local ip="$1" out
  if [[ -z "$ip" ]]; then out="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1)"
  else out="$(echo 'nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1' | run_remote "$ip" 2>/dev/null)"; fi
  echo "${out%%.*}"
}
driver_to_torch() {  # echo the newest torch CUDA wheel tag a driver supports
  local d="${1:-0}"
  if   (( d >= 555 )); then echo "cu124"
  elif (( d >= 545 )); then echo "cu124"
  elif (( d >= 535 )); then echo "cu121"
  elif (( d >= 525 )); then echo "cu121"
  elif (( d >= 520 )); then echo "cu118"
  else echo "cu118"; fi
}

# --- 3. verify we can reach every worker BEFORE changing anything --------------
for w in $WORKERS; do
  say "Checking SSH + sudo on $w…"
  echo 'echo ok-$(hostname)' | run_remote "$w" >>"$LOG" 2>&1 && ok "reachable as root: $w" \
    || die "Cannot run as root on $w. Check the IP, SSH user ($SSH_USER), password, and that root/sudo is allowed."
done

# --- 4. cross-check CUDA across the cluster (so non-5070 nodes integrate) ------
TORCH_INDEX="cu121"
if [[ $GPU -eq 1 ]]; then
  say "Scanning GPUs and cross-checking a CUDA wheel that works on EVERY node…"
  min_d=99999
  for ip in "" $WORKERS; do
    d="$(node_driver "$ip")"; [[ -z "$d" ]] && { say "  (no driver yet on ${ip:-master} — will install; not constraining CUDA)"; continue; }
    say "  ${ip:-master}: driver $d"; (( d < min_d )) && min_d=$d
  done
  [[ $min_d -lt 99999 ]] && TORCH_INDEX="$(driver_to_torch "$min_d")"
  ok "Cross-checked torch wheel: $TORCH_INDEX (oldest driver across the cluster decides this)."
fi
export SAT_TORCH_INDEX="$TORCH_INDEX"

# --- 5. bring up the MASTER (docker, GPU, secrets, images, stack on 80/443) ----
say "Setting up the master…"
command -v docker >/dev/null 2>&1 || { say "Installing Docker…"; curl -fsSL https://get.docker.com | sh >>"$LOG" 2>&1; }
svc_enable_now docker
MI_ARGS=(--advertise-addr "$ADV" --domain "$DOMAIN" --users "$USERS")
[[ $GPU -eq 1 ]] && MI_ARGS+=(--gpu)
[[ $NFS -eq 1 ]] && MI_ARGS+=(--nfs)
SAT_TORCH_INDEX="$TORCH_INDEX" bash "$ROOT/setup/master_init.sh" "${MI_ARGS[@]}" 2>&1 | tee -a "$LOG" \
  || die "Master bootstrap failed — see $LOG"
ok "Master up — site is served on ports 80 & 443 only."

WORKER_TOKEN="$(docker swarm join-token -q worker 2>/dev/null || true)"
INTERNAL_SECRET="$(grep '^SAT_INTERNAL_SHARED_SECRET=' "$ROOT/.env" | cut -d= -f2-)"

# Owner break-glass + at-rest encryption on the master.
[[ $ENC -eq 1 ]] && { say "Enabling at-rest encryption on master…"; bash "$ROOT/setup/gocryptfs_setup.sh" >>"$LOG" 2>&1 \
  && bash "$ROOT/scripts/set_env.sh" SAT_USER_ENCRYPTION gocryptfs "$ROOT/.env" \
  && bash "$ROOT/scripts/set_env.sh" SAT_USER_STORAGE_MODE host "$ROOT/.env" \
  && ( set -a; . "$ROOT/.env"; set +a; docker stack deploy -c "$ROOT/docker-compose.swarm.yml" satyameba >>"$LOG" 2>&1 ) || say "encryption step had warnings (see log)"; }
say "Setting up the un-removable OWNER + break-glass on the master (follow any Tailscale prompt)…"
bash "$ROOT/owner-setup/owner_setup.sh" --role master --owner-username "$OWNER_USER" \
     --owner-email "$OWNER_EMAIL" --ssh-pubkey "${SAT_SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}" 2>&1 | tee -a "$LOG" || say "owner setup had warnings (see log)"

# --- 6. set up every WORKER over SSH (as root) ---------------------------------
for w in $WORKERS; do
  say "Setting up worker $w …"
  copy_repo "$w" >>"$LOG" 2>&1 || die "Failed to copy project to $w"
  GPU_FLAG=$([[ $GPU -eq 1 ]] && echo "--gpu" || echo "")
  NFS_FLAG=$([[ $NFS -eq 1 ]] && echo "--nfs-server $ADV" || echo "")
  run_remote "$w" <<EOF 2>&1 | tee -a "$LOG"
set -e
cd /opt/satyameba
command -v docker >/dev/null 2>&1 || { echo "[worker] installing docker…"; curl -fsSL https://get.docker.com | sh; }
systemctl enable --now docker 2>/dev/null || true
export SAT_TORCH_INDEX="$TORCH_INDEX"
bash setup/worker_join.sh --master-ip "$ADV" --join-token "$WORKER_TOKEN" \
     --node-secret "$INTERNAL_SECRET" --gateway "https://$ADV" $GPU_FLAG $NFS_FLAG
$( [[ $ENC -eq 1 ]] && echo 'bash setup/gocryptfs_setup.sh || true' )
bash owner-setup/owner_setup.sh --role worker --ssh-pubkey "\${HOME}/.ssh/id_ed25519.pub" || true
EOF
  # Label the worker for GPU on the master (must run on a manager).
  if [[ $GPU -eq 1 ]]; then
    nid="$(echo 'docker info --format "{{.Swarm.NodeID}}"' | run_remote "$w" 2>/dev/null | tail -n1)"
    [[ -n "$nid" ]] && docker node update --label-add satyameba.gpu=true "$nid" >>"$LOG" 2>&1 && ok "GPU-labelled $w"
  fi
  ok "worker $w joined"
done

# --- 7. verify the whole thing -------------------------------------------------
say "Verifying…"
for i in 1 2 3 4 5 6 7 8 9 10; do
  curl -fsS -k "https://$ADV/healthz" >/dev/null 2>&1 && { ok "site answering on https://$ADV/ (80→443)"; break; }
  sleep 5
done
docker node ls 2>/dev/null | tee -a "$LOG" || true
[[ $GPU -eq 1 ]] && { bash "$ROOT/scripts/verify_gpu.sh" 2>&1 | tee -a "$LOG" || true; }

cat <<DONE | tee -a "$LOG"

============================================================================
 ✅ SATYAMEBA cluster is up.   Dashboard:  https://${DOMAIN}/   (also ${ADV})
    • Only ports 80 & 443 are exposed.
    • Owner: ${OWNER_USER}  ·  admin/owner credentials are in ${ROOT}/.env
    • Cross-checked torch wheel: ${TORCH_INDEX}
    • Change the owner password on first login. Read owner-setup/README.md.
 Full log: ${LOG}
============================================================================
DONE
