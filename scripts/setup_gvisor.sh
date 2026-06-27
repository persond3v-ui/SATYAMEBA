#!/usr/bin/env bash
# Install gVisor (runsc) and register it as a Docker runtime on this node, so
# notebooks can run in a much stronger sandbox (syscall interception) that
# defends against container-escape by a malicious user.
#
#   sudo ./scripts/setup_gvisor.sh
#   then set SAT_SANDBOX_RUNTIME=runsc in .env and redeploy.
#
# Run on EVERY node that will spawn notebooks. GPU + gVisor is limited — keep
# GPU notebooks on the default runtime if you hit issues.
set -euo pipefail

ARCH="$(uname -m)"
URL="https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}"
say() { printf "\033[1;32m[gvisor]\033[0m %s\n" "$*"; }

if command -v runsc >/dev/null 2>&1; then
  say "runsc already installed: $(runsc --version | head -1)"
else
  say "Downloading runsc + containerd-shim-runsc-v1…"
  TMP="$(mktemp -d)"
  ( cd "$TMP"
    for f in runsc containerd-shim-runsc-v1; do
      wget -q "${URL}/${f}" "${URL}/${f}.sha512"
      sha512sum -c "${f}.sha512"
      chmod a+rx "$f"
      mv "$f" /usr/local/bin/
    done )
  rm -rf "$TMP"
  say "Installed: $(runsc --version | head -1)"
fi

# Register runsc with Docker (merge into daemon.json without clobbering).
python3 - <<'PY'
import json, os
path = "/etc/docker/daemon.json"
data = {}
if os.path.exists(path):
    try:
        data = json.load(open(path))
    except Exception:
        data = {}
data.setdefault("runtimes", {})["runsc"] = {"path": "/usr/local/bin/runsc"}
json.dump(data, open(path, "w"), indent=2)
print("[gvisor] registered runsc runtime in", path)
PY

systemctl restart docker 2>/dev/null || service docker restart || true
say "Done. Set SAT_SANDBOX_RUNTIME=runsc in .env and redeploy to enforce it."
