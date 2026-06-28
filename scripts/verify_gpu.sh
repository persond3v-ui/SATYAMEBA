#!/usr/bin/env bash
# ===========================================================================
# Verify SATYAMEBA's GPU scheduling assumptions on REAL hardware.
#
#   sudo ./scripts/verify_gpu.sh
#
# SATYAMEBA's exclusive-vs-shared GPU model rests on three things being true on
# a GPU node. This script checks each and prints PASS/FAIL so you don't have to
# take the design on faith:
#
#   1. The kernel driver works            (nvidia-smi).
#   2. default-runtime=nvidia is set       (so SHARED notebooks, which take no
#      Swarm reservation, still see the card via NVIDIA_VISIBLE_DEVICES=all).
#   3. NVIDIA_VISIBLE_DEVICES gates access  (all → GPU visible; void → hidden,
#      which is how CPU notebooks are kept off the GPU).
#   4. The GPU is advertised to Swarm       (node-generic-resources) so EXCLUSIVE
#      notebooks can reserve the whole card.
#
# Reference stack this was written against (pin yours near these):
#   NVIDIA driver >= 555 (RTX 5070 / Blackwell) · nvidia-container-toolkit >= 1.14
#   Docker >= 24 · CUDA base image 12.x
# ===========================================================================
set -uo pipefail
CUDA_IMG="${SAT_CUDA_TEST_IMAGE:-nvidia/cuda:12.4.1-base-ubuntu22.04}"
PASS=0; FAIL=0
ok()   { printf "  \033[1;32mPASS\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[1;31mFAIL\033[0m %s\n" "$1"; FAIL=$((FAIL+1)); }
info() { printf "\033[1;36m[verify-gpu]\033[0m %s\n" "$1"; }

info "1. Kernel driver"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  ok "nvidia-smi works ($(nvidia-smi --query-gpu=name,driver_version --format=csv,noheader | head -n1))"
else
  bad "nvidia-smi not working — install the NVIDIA driver (555+ for RTX 5070), reboot."
fi

info "2. Docker default-runtime = nvidia"
DR="$(docker info --format '{{ .DefaultRuntime }}' 2>/dev/null || echo unknown)"
if [[ "$DR" == "nvidia" ]]; then ok "default-runtime is nvidia"
else bad "default-runtime is '$DR' — run scripts/setup_gpu_runtime.sh (shared notebooks need this)"; fi

info "3. NVIDIA_VISIBLE_DEVICES gating (this is how shared vs CPU-only is enforced)"
if docker run --rm -e NVIDIA_VISIBLE_DEVICES=all "$CUDA_IMG" nvidia-smi -L >/dev/null 2>&1; then
  ok "NVIDIA_VISIBLE_DEVICES=all  -> GPU visible (SHARED notebooks can co-tenant)"
else
  bad "=all did not expose a GPU — check the toolkit (scripts/setup_nvidia_toolkit.sh)"
fi
if docker run --rm -e NVIDIA_VISIBLE_DEVICES=void "$CUDA_IMG" nvidia-smi -L >/dev/null 2>&1; then
  bad "=void STILL saw a GPU — CPU notebooks would leak onto the card!"
else
  ok "NVIDIA_VISIBLE_DEVICES=void -> GPU hidden (CPU notebooks stay off the GPU)"
fi

info "4. GPU advertised to Swarm (for EXCLUSIVE reservation)"
if [[ -f /etc/docker/daemon.json ]] && grep -q "node-generic-resources" /etc/docker/daemon.json; then
  ok "node-generic-resources present in daemon.json"
  if docker info 2>/dev/null | grep -q "Swarm: active"; then
    SELF="$(docker node ls --filter role=manager --format '{{.Hostname}}' 2>/dev/null | head -n1)"
    if [[ -n "$SELF" ]] && docker node inspect "$SELF" --format '{{json .Description.Resources.GenericResources}}' 2>/dev/null | grep -qi gpu; then
      ok "Swarm sees this node's GPU as a generic resource"
    else
      info "  (run on a manager that has the GPU to confirm the generic resource is seen)"
    fi
  else
    info "  (not in a swarm yet — exclusive reservation is only exercised in Swarm mode)"
  fi
else
  bad "no node-generic-resources — run scripts/setup_gpu_runtime.sh so EXCLUSIVE notebooks can reserve the GPU"
fi

echo
info "Manual final check (two concurrent kernels on one node):"
echo "    Launch two GPU notebooks for two users on a single GPU node and run a"
echo "    small torch job in each at once — both should make progress (concurrent"
echo "    sharing). nvidia-smi on the host should list both python processes."
echo
info "Result: ${PASS} passed, ${FAIL} failed."
[[ "$FAIL" -eq 0 ]] && { info "GPU path looks good."; exit 0; } || { info "Fix the FAILs above, then re-run."; exit 1; }
