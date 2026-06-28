#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — REMOTE node join over Tailscale (off-VLAN / different location).
#
# This is a SEPARATE wizard on purpose: same-VLAN nodes use worker_join.sh and
# need NO Tailscale. Use THIS one only when the node is not on the master's LAN
# (e.g. another building, a home machine). It builds a WireGuard mesh with
# Tailscale (outbound-only, no router/port-forward config) and joins the swarm
# over the tailnet so the overlay works across NAT.
#
#   sudo ./setup/remote_node_join.sh \
#        --master-ts-ip 100.x.y.z --join-token SWMTKN-... \
#        --node-secret <secret> [--authkey tskey-...] [--gpu] [--compute-only]
#
#   --master-ts-ip  the master's Tailscale (100.x.y.z) address.
#   --authkey       a Tailscale auth key for unattended join (else interactive).
#   --gpu           this remote node has an NVIDIA GPU to schedule on.
#   --compute-only  don't keep persistent user data here (untrusted location):
#                   the node is labelled so the operator can keep NFS off it.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/lib_pkg.sh"

MASTER_TS=""; JOIN_TOKEN=""; NODE_SECRET=""; AUTHKEY=""; GPU=0; COMPUTE_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --master-ts-ip) MASTER_TS="$2"; shift ;;
    --join-token)   JOIN_TOKEN="$2"; shift ;;
    --node-secret)  NODE_SECRET="$2"; shift ;;
    --authkey)      AUTHKEY="$2"; shift ;;
    --gpu)          GPU=1 ;;
    --compute-only) COMPUTE_ONLY=1 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
say() { printf "\033[1;32m[remote]\033[0m %s\n" "$*"; }

[[ -z "$MASTER_TS" || -z "$JOIN_TOKEN" || -z "$NODE_SECRET" ]] && {
  echo "Missing required args. See header for usage."; exit 1; }
command -v docker >/dev/null || { echo "Docker not found. Run the setup wizard first."; exit 1; }

pkg_detect

# 1. Install + bring up Tailscale (the official installer covers all distros).
if ! command -v tailscale >/dev/null 2>&1; then
  say "Installing Tailscale…"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
say "Bringing up the tailnet (outbound-only WireGuard; no router config)…"
if [[ -n "$AUTHKEY" ]]; then
  _sudo tailscale up --authkey "$AUTHKEY" --accept-routes
else
  _sudo tailscale up --accept-routes || true
  say "If a login URL was printed, approve this node in your Tailscale admin, then re-run."
fi
MY_TS="$(tailscale ip -4 2>/dev/null | head -n1)"
[[ -z "$MY_TS" ]] && { echo "No Tailscale IP yet — approve the node and re-run."; exit 1; }
say "This node's tailnet IP: $MY_TS"

HOSTNAME_S="$(hostname)"
GATEWAY="https://${MASTER_TS}"

# 2. Configure GPU runtime (toolkit + advertises the GPU + default-runtime=nvidia).
if [[ $GPU -eq 1 ]]; then
  command -v nvidia-ctk >/dev/null 2>&1 || { say "Installing NVIDIA Container Toolkit…"; bash scripts/setup_nvidia_toolkit.sh || true; }
  say "Configuring GPU runtime…"; bash scripts/setup_gpu_runtime.sh gpu || true
fi

# 3. Join the swarm OVER THE TAILNET (advertise/listen on the tailnet IP).
if docker info 2>/dev/null | grep -q "Swarm: active"; then
  say "Already in a swarm."
else
  say "Joining swarm at ${MASTER_TS}:2377 over the tailnet…"
  docker swarm join --advertise-addr "${MY_TS}" --listen-addr "${MY_TS}:2377" \
    --token "$JOIN_TOKEN" "${MASTER_TS}:2377"
fi

# 4. Build the notebook image locally.
say "Building notebook sandbox image…"
NB_GPU_ARG=$([[ $GPU -eq 1 ]] && echo "--build-arg SAT_GPU_BUILD=true" || echo "")
docker build -q $NB_GPU_ARG -t satyameba/notebook:latest ./jupyterhub/singleuser

# 5. Register with the gateway (over the tailnet), with remote/compute-only labels.
NODE_TOKEN="$(printf '%s' "$HOSTNAME_S" | openssl dgst -sha256 -hmac "$NODE_SECRET" | awk '{print $2}')"
LBL="\"remote\":\"tailscale\""
[[ $GPU -eq 1 ]] && LBL="${LBL},\"gpu\":\"nvidia\""
[[ $COMPUTE_ONLY -eq 1 ]] && LBL="${LBL},\"compute_only\":\"true\""
say "Registering with gateway at ${GATEWAY} …"
curl -fsS -k -X POST "${GATEWAY}/api/nodes/register" \
  -H "Content-Type: application/json" -H "X-SAT-Node-Token: ${NODE_TOKEN}" \
  -d "{\"hostname\":\"${HOSTNAME_S}\",\"ip\":\"${MY_TS}\",\"role\":\"worker\",\"labels\":{${LBL}}}" \
  >/dev/null && say "Registered ✔" || say "Registration failed (node still joined swarm)."

# 6. node.env (for the TUI) + heartbeat timer.
mkdir -p /etc/satyameba
cat >/etc/satyameba/node.env <<EOF
SAT_GATEWAY_URL=${GATEWAY}
SAT_NODE_HOSTNAME=${HOSTNAME_S}
SAT_NODE_TOKEN=${NODE_TOKEN}
EOF
if command -v systemctl >/dev/null 2>&1; then
  cat >/etc/systemd/system/satyameba-heartbeat.service <<EOF
[Unit]
Description=SATYAMEBA remote worker heartbeat
[Service]
Type=oneshot
ExecStart=/bin/bash -c 'curl -fsS -k -X POST ${GATEWAY}/api/nodes/heartbeat -H "Content-Type: application/json" -H "X-SAT-Node-Token: ${NODE_TOKEN}" -d "{\\"hostname\\":\\"${HOSTNAME_S}\\",\\"ip\\":\\"${MY_TS}\\",\\"role\\":\\"worker\\",\\"labels\\":{${LBL}}}"'
EOF
  cat >/etc/systemd/system/satyameba-heartbeat.timer <<EOF
[Unit]
Description=SATYAMEBA remote worker heartbeat timer
[Timer]
OnBootSec=30
OnUnitActiveSec=30
[Install]
WantedBy=timers.target
EOF
  systemctl daemon-reload && systemctl enable --now satyameba-heartbeat.timer >/dev/null 2>&1 || true
fi

if [[ $GPU -eq 1 ]]; then
  SWARM_NODE_ID="$(docker info --format '{{.Swarm.NodeID}}')"
  say "On the MASTER, label this node for GPU scheduling:"
  echo "    docker node update --label-add satyameba.gpu=true ${SWARM_NODE_ID}"
fi
say "Remote node joined over Tailscale. It now appears under Admin → Nodes."
