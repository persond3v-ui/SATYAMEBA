#!/usr/bin/env bash
# ===========================================================================
# Configure a node's Docker daemon to advertise its NVIDIA GPUs as a Swarm
# generic resource, so SwarmSpawner can reserve GPUs for GPU notebooks.
#
#   sudo ./scripts/setup_gpu_runtime.sh [resource_name]   # default: gpu
#
# Requires: NVIDIA driver + nvidia-container-toolkit (the setup wizard installs
# these). Safe no-op on nodes without a GPU. Merges into existing daemon.json.
# ===========================================================================
set -euo pipefail
RES="${1:-gpu}"

command -v nvidia-smi >/dev/null 2>&1 || { echo "[gpu] no nvidia-smi; skipping."; exit 0; }
command -v nvidia-ctk >/dev/null 2>&1 || { echo "[gpu] nvidia-container-toolkit missing; run the wizard first."; exit 1; }

# Register the nvidia runtime with docker (idempotent).
nvidia-ctk runtime configure --runtime=docker >/dev/null 2>&1 || true

mapfile -t UUIDS < <(nvidia-smi --query-gpu=uuid --format=csv,noheader | sed 's/^ *//;s/ *$//')
[[ ${#UUIDS[@]} -eq 0 ]] && { echo "[gpu] no GPUs detected; skipping."; exit 0; }

# Merge node-generic-resources into /etc/docker/daemon.json without clobbering.
python3 - "$RES" "${UUIDS[@]}" <<'PY'
import json, os, sys
res, uuids = sys.argv[1], sys.argv[2:]
path = "/etc/docker/daemon.json"
data = {}
if os.path.exists(path):
    try:
        data = json.load(open(path))
    except Exception:
        data = {}
data["node-generic-resources"] = [f"{res}={u}" for u in uuids]
# Make the nvidia runtime the DEFAULT so concurrent-share notebooks (which take
# no Swarm GPU reservation) can still see the card via NVIDIA_VISIBLE_DEVICES.
# Exclusive notebooks reserve the generic resource instead. CPU notebooks get
# NVIDIA_VISIBLE_DEVICES=void so the default runtime doesn't leak the GPU.
runtimes = data.get("runtimes", {})
if "nvidia" in runtimes or os.path.exists("/usr/bin/nvidia-container-runtime"):
    data.setdefault("runtimes", {}).setdefault(
        "nvidia", {"path": "nvidia-container-runtime", "runtimeArgs": []})
    data["default-runtime"] = "nvidia"
json.dump(data, open(path, "w"), indent=2)
print(f"[gpu] wrote {path} advertising {len(uuids)} GPU(s) as resource '{res}' "
      f"(default-runtime=nvidia for concurrent sharing)")
PY

# Enable the swarm-resource mapping in the nvidia container runtime config.
CFG=/etc/nvidia-container-runtime/config.toml
RES_ENV="DOCKER_RESOURCE_$(echo "$RES" | tr '[:lower:]-' '[:upper:]_')"
if [[ -f "$CFG" ]]; then
  if grep -qE '^\s*#?\s*swarm-resource' "$CFG"; then
    sed -i "s|^\s*#\?\s*swarm-resource.*|swarm-resource = \"${RES_ENV}\"|" "$CFG"
  else
    echo "swarm-resource = \"${RES_ENV}\"" >> "$CFG"
  fi
  echo "[gpu] set swarm-resource = ${RES_ENV}"
fi

systemctl restart docker 2>/dev/null || service docker restart || true
echo "[gpu] done — Docker now advertises GPUs to Swarm (resource '${RES}')."
