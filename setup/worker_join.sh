#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — worker join. Run on each Debian worker (same VLAN as master).
#
#   sudo ./setup/worker_join.sh --master-ip IP --join-token TOK \
#        --node-secret SECRET --gateway https://IP [--gpu] [--master-ssh u@host]
#
# Steps:
#   1. join the swarm  (master accepts the connection on :2377)
#   2. build the notebook sandbox image locally so SwarmSpawner can place it
#   3. register this node with the gateway (shows up in the admin Nodes view)
#   4. if --gpu: label the node in swarm (so GPU notebooks land here)
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

MASTER_IP=""; JOIN_TOKEN=""; NODE_SECRET=""; GATEWAY=""; GPU=0; MASTER_SSH=""; NFS_SERVER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --master-ip) MASTER_IP="$2"; shift ;;
    --join-token) JOIN_TOKEN="$2"; shift ;;
    --node-secret) NODE_SECRET="$2"; shift ;;
    --gateway) GATEWAY="$2"; shift ;;
    --gpu) GPU=1 ;;
    --master-ssh) MASTER_SSH="$2"; shift ;;
    --nfs-server) NFS_SERVER="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
say() { printf "\033[1;36m[worker]\033[0m %s\n" "$*"; }

[[ -z "$MASTER_IP" || -z "$JOIN_TOKEN" || -z "$NODE_SECRET" ]] && {
  echo "Missing required args. See header for usage."; exit 1; }

command -v docker >/dev/null || { echo "Docker not found. Run setup/satyameba_setup.py first."; exit 1; }

HOSTNAME_S="$(hostname)"
IP_S="$(hostname -I 2>/dev/null | awk '{print $1}')"
GATEWAY="${GATEWAY:-https://$MASTER_IP}"

# 1. Join the swarm.
if docker info 2>/dev/null | grep -q "Swarm: active"; then
  say "Already part of a swarm."
else
  say "Joining swarm at ${MASTER_IP}:2377 …"
  docker swarm join --token "$JOIN_TOKEN" "${MASTER_IP}:2377"
fi

# 1b. Configure the GPU runtime so this node advertises its GPUs to Swarm.
if [[ $GPU -eq 1 ]]; then
  say "Configuring NVIDIA GPU runtime…"
  bash scripts/setup_gpu_runtime.sh gpu || say "GPU runtime setup skipped/failed (continuing)."
fi

# 1c. Mount the shared NFS store so per-user work follows users to this node.
if [[ -n "$NFS_SERVER" ]]; then
  say "Mounting shared NFS storage from ${NFS_SERVER}…"
  bash scripts/setup_nfs.sh client --server "$NFS_SERVER" || say "NFS mount failed (continuing)."
fi

# 2. Build the notebook sandbox image locally.
say "Building notebook sandbox image…"
NB_GPU_ARG=$([[ $GPU -eq 1 ]] && echo "--build-arg SAT_GPU_BUILD=true" || echo "")
docker build -q $NB_GPU_ARG -t satyameba/notebook:latest ./jupyterhub/singleuser

# 3. Register with the gateway. The node token is HMAC(node_secret, hostname).
NODE_TOKEN="$(printf '%s' "$HOSTNAME_S" | openssl dgst -sha256 -hmac "$NODE_SECRET" | awk '{print $2}')"
GPU_LABEL=$([[ $GPU -eq 1 ]] && echo '"gpu":"nvidia"' || echo '"gpu":""')
say "Registering with gateway at ${GATEWAY} …"
curl -fsS -k -X POST "${GATEWAY}/api/nodes/register" \
  -H "Content-Type: application/json" \
  -H "X-SAT-Node-Token: ${NODE_TOKEN}" \
  -d "{\"hostname\":\"${HOSTNAME_S}\",\"ip\":\"${IP_S}\",\"role\":\"worker\",\"labels\":{${GPU_LABEL}}}" \
  >/dev/null && say "Registered ✔" || say "Registration call failed (node still joined swarm)."

# Record connection details for the on-console TUI dashboard.
mkdir -p /etc/satyameba
cat >/etc/satyameba/node.env <<EOF
SAT_GATEWAY_URL=${GATEWAY}
SAT_NODE_HOSTNAME=${HOSTNAME_S}
SAT_NODE_TOKEN=${NODE_TOKEN}
EOF

# Heartbeat timer (systemd) so the admin dashboard sees this node as online.
if command -v systemctl >/dev/null 2>&1; then
  cat >/etc/systemd/system/satyameba-heartbeat.service <<EOF
[Unit]
Description=SATYAMEBA worker heartbeat
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'curl -fsS -k -X POST ${GATEWAY}/api/nodes/heartbeat -H "Content-Type: application/json" -H "X-SAT-Node-Token: ${NODE_TOKEN}" -d "{\\"hostname\\":\\"${HOSTNAME_S}\\",\\"ip\\":\\"${IP_S}\\",\\"role\\":\\"worker\\",\\"labels\\":{${GPU_LABEL}}}"'
EOF
  cat >/etc/systemd/system/satyameba-heartbeat.timer <<EOF
[Unit]
Description=SATYAMEBA worker heartbeat timer
[Timer]
OnBootSec=30
OnUnitActiveSec=30
[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload && systemctl enable --now satyameba-heartbeat.timer >/dev/null 2>&1 || true
  say "Heartbeat timer installed."
fi

# 4. GPU label in swarm (must be applied on a manager).
if [[ $GPU -eq 1 ]]; then
  SWARM_NODE_ID="$(docker info --format '{{.Swarm.NodeID}}')"
  if [[ -n "$MASTER_SSH" ]]; then
    say "Labelling node for GPU on master via SSH…"
    ssh "$MASTER_SSH" "docker node update --label-add satyameba.gpu=true ${SWARM_NODE_ID}" \
      && say "GPU label applied." || say "Could not SSH-label; run the command below on the master."
  fi
  echo
  say "If GPU label was not applied automatically, run THIS on the master:"
  echo "    docker node update --label-add satyameba.gpu=true ${SWARM_NODE_ID}"
fi

say "Worker join complete."
