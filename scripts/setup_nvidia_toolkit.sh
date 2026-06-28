#!/usr/bin/env bash
# ===========================================================================
# Install the NVIDIA Container Toolkit (so Docker can expose GPUs) on ANY
# mainstream distro, and sanity-check the kernel driver.
#
#   sudo ./scripts/setup_nvidia_toolkit.sh
#
# What it does / does NOT do:
#   * DOES install nvidia-container-toolkit from NVIDIA's official repo (apt /
#     dnf / yum / zypper) and register the runtime with Docker.
#   * Does NOT install the kernel DRIVER. The driver is a host prerequisite that
#     often needs Secure-Boot signing + a reboot, so we DETECT it and give clear
#     instructions instead of pretending. RTX 5070 (Blackwell) needs a 555+ driver.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib_pkg.sh"
pkg_detect || true
say() { printf "\033[1;32m[nvidia]\033[0m %s\n" "$*"; }

# --- 1. kernel driver check (host prerequisite) ----------------------------
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  say "Driver OK: $(nvidia-smi --query-gpu=driver_version,name --format=csv,noheader | head -n1)"
else
  say "NVIDIA kernel driver not detected."
  case "$PKG_OS" in
    debian) say "Install it, then re-run:  sudo apt-get install -y nvidia-driver  (or the 555+ CUDA-repo driver for RTX 5070), then reboot." ;;
    fedora|rhel) say "Install it, then re-run:  sudo dnf install -y akmod-nvidia  (RPM Fusion / CUDA repo, 555+ for RTX 5070), then reboot." ;;
    arch)   say "Install it, then re-run:  sudo pacman -S nvidia  (or nvidia-open for Blackwell), then reboot." ;;
    suse)   say "Install the NVIDIA driver from the openSUSE NVIDIA repo (555+), then reboot." ;;
    *)      say "Install your distro's NVIDIA driver (555+ for RTX 5070), then reboot." ;;
  esac
  say "Continuing to install the container toolkit anyway (it's still needed)."
fi

# --- 2. NVIDIA Container Toolkit repo + install ----------------------------
if command -v nvidia-ctk >/dev/null 2>&1; then
  say "nvidia-container-toolkit already installed ($(nvidia-ctk --version 2>/dev/null | head -n1))."
else
  say "Adding NVIDIA Container Toolkit repository…"
  case "$PKG" in
    apt)
      install -d -m 0755 /usr/share/keyrings
      curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
      curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        > /etc/apt/sources.list.d/nvidia-container-toolkit.list
      pkg_refresh; pkg_install nvidia-container-toolkit ;;
    dnf|yum)
      curl -fsSL https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo \
        -o /etc/yum.repos.d/nvidia-container-toolkit.repo
      pkg_install nvidia-container-toolkit ;;
    zypper)
      zypper ar -f https://nvidia.github.io/libnvidia-container/stable/rpm/nvidia-container-toolkit.repo || true
      pkg_install nvidia-container-toolkit ;;
    pacman)
      say "On Arch, install 'nvidia-container-toolkit' from the AUR, then re-run." ;;
    *)
      say "Unsupported package manager for auto-install; install nvidia-container-toolkit manually." ;;
  esac
fi

# --- 3. register the runtime with Docker -----------------------------------
if command -v nvidia-ctk >/dev/null 2>&1; then
  say "Registering the nvidia runtime with Docker…"
  nvidia-ctk runtime configure --runtime=docker >/dev/null 2>&1 || true
  systemctl restart docker 2>/dev/null || service docker restart 2>/dev/null || true
fi

say "Done. Next: scripts/setup_gpu_runtime.sh (advertises the GPU + default-runtime),"
say "then scripts/verify_gpu.sh to confirm the whole path works."
