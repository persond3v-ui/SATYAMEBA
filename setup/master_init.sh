#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — master/control-plane bootstrap.
#
#   ./setup/master_init.sh [--single] [--advertise-addr IP] [--gpu] [--domain D]
#
#   --single          Run everything on this one machine via docker compose
#                     (great for a demo). Default is multi-node Docker Swarm.
#   --advertise-addr  VLAN IP other nodes use to reach this master.
#   --gpu             This master also has an NVIDIA GPU to schedule on.
#   --domain          TLS/CORS domain (default satyameba.local).
#
# Idempotent: safe to re-run. Prints the exact command workers should run.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

MODE="swarm"; ADV=""; GPU=0; DOMAIN="satyameba.local"; USERS=8; NFS=0; NFS_SUBNET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --single) MODE="compose" ;;
    --advertise-addr) ADV="$2"; shift ;;
    --gpu) GPU=1 ;;
    --domain) DOMAIN="$2"; shift ;;
    --users) USERS="$2"; shift ;;
    --nfs) NFS=1 ;;
    --nfs-subnet) NFS_SUBNET="$2"; NFS=1; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done

say() { printf "\033[1;33m[satyameba]\033[0m %s\n" "$*"; }

command -v docker >/dev/null || { echo "Docker not found. Run setup/satyameba_setup.py first."; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "docker compose v2 required."; exit 1; }

[[ -z "$ADV" ]] && ADV="$(hostname -I 2>/dev/null | awk '{print $1}')"
say "Advertise address: ${ADV:-<unset>}   mode: $MODE   domain: $DOMAIN"

say "Generating secrets…"
bash scripts/gen_secrets.sh --domain="$DOMAIN"

say "Scanning host storage / RAM / CPU and sizing for ${USERS} users…"
bash scripts/scan_resources.sh --users "$USERS"

if [[ $NFS -eq 1 ]]; then
  [[ -z "$NFS_SUBNET" && -n "$ADV" ]] && NFS_SUBNET="$(echo "$ADV" | awk -F. '{print $1"."$2"."$3".0/24"}')"
  say "Setting up shared NFS storage (subnet ${NFS_SUBNET}) so user work follows them across nodes…"
  bash scripts/setup_nfs.sh server --subnet "$NFS_SUBNET"
  sed -i 's/^SAT_USER_STORAGE_MODE=.*/SAT_USER_STORAGE_MODE=host/' .env
  say "Per-user storage mode set to 'host' (NFS-backed)."
fi

if [[ $GPU -eq 1 ]] || command -v nvidia-smi >/dev/null 2>&1; then
  command -v nvidia-ctk >/dev/null 2>&1 || { say "Installing NVIDIA Container Toolkit…"; bash scripts/setup_nvidia_toolkit.sh || say "toolkit install skipped (continuing)."; }
  say "Configuring NVIDIA GPU runtime for Swarm…"
  GPU_RES="$(grep '^SAT_GPU_RESOURCE=' .env | cut -d= -f2-)"; GPU_RES="${GPU_RES:-gpu}"
  bash scripts/setup_gpu_runtime.sh "$GPU_RES" || say "GPU runtime setup skipped/failed (continuing)."
fi

say "Building images (gateway, jupyterhub, edge, notebook)…"
docker build -q -t satyameba/gateway:latest ./gateway
docker build -q -t satyameba/jupyterhub:latest ./jupyterhub
docker build -q -t satyameba/edge:latest ./frontend
NB_GPU_ARG=$([[ $GPU -eq 1 ]] && echo "--build-arg SAT_GPU_BUILD=true" || echo "")
docker build -q $NB_GPU_ARG --build-arg SAT_TORCH_INDEX="${SAT_TORCH_INDEX:-cu121}" -t satyameba/notebook:latest ./jupyterhub/singleuser

INTERNAL_SECRET="$(grep '^SAT_INTERNAL_SHARED_SECRET=' .env | cut -d= -f2-)"

if [[ "$MODE" == "compose" ]]; then
  [[ $GPU -eq 1 ]] && sed -i 's/^SAT_GPU_ENABLED=.*/SAT_GPU_ENABLED=true/' .env
  say "Starting single-host stack…"
  docker compose up -d
  say "Up. Open: https://${DOMAIN}/  (admin password is in .env)"
  exit 0
fi

# ---- Swarm path -----------------------------------------------------------
if ! docker info 2>/dev/null | grep -q "Swarm: active"; then
  say "Initialising Docker Swarm…"
  docker swarm init --advertise-addr "$ADV" >/dev/null
fi

# Label this manager for GPU if requested / detected.
SELF_NODE="$(docker node ls --filter role=manager --format '{{.Hostname}}' | head -n1)"
if [[ $GPU -eq 1 ]] || command -v nvidia-smi >/dev/null 2>&1; then
  docker node update --label-add satyameba.gpu=true "$SELF_NODE" >/dev/null || true
  sed -i 's/^SAT_GPU_ENABLED=.*/SAT_GPU_ENABLED=true/' .env
  say "Master labelled satyameba.gpu=true"
fi

say "Deploying stack 'satyameba'…"
source "$ROOT/scripts/load_env.sh"; load_env "$ROOT/.env"
docker stack deploy -c docker-compose.swarm.yml satyameba

WORKER_TOKEN="$(docker swarm join-token -q worker)"
cat <<BANNER

============================================================================
 SATYAMEBA master is up.   Dashboard:  https://${DOMAIN}/
 Admin login is in .env (SAT_BOOTSTRAP_ADMIN_*). CHANGE IT after first login.

 To add a worker, run THIS on each Debian node (same VLAN):

   sudo ./setup/worker_join.sh \\
        --master-ip ${ADV} \\
        --join-token ${WORKER_TOKEN} \\
        --node-secret ${INTERNAL_SECRET} \\
        --gateway https://${ADV} \\
        $([[ $NFS -eq 1 ]] && echo "--nfs-server ${ADV} ")\\
        [--gpu] [--master-ssh user@${ADV}]

 $([[ $NFS -eq 1 ]] && echo "Shared NFS storage is ON: per-user work follows users across nodes." || echo "Tip: re-run with --nfs for shared storage so user work follows them across nodes.")
============================================================================
BANNER
