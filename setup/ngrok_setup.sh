#!/usr/bin/env bash
# ===========================================================================
# Expose the master to the internet via ngrok (asks for the token ONCE).
#
#   sudo ./setup/ngrok_setup.sh                 # prompts for the authtoken
#   sudo ./setup/ngrok_setup.sh --token <TOK>   # non-interactive
#
# Installs ngrok, saves the token, runs a boot service that forwards the HTTPS
# edge (port 443) to a public URL, and sets a cluster-wide shell alias
# `satyameba-url` so anyone on any node can print the public address.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT/scripts/lib_pkg.sh"
say() { printf "\033[1;35m[ngrok]\033[0m %s\n" "$*"; }
pkg_detect || true

TOKEN=""; [[ "${1:-}" == "--token" ]] && TOKEN="${2:-}"
[[ $EUID -ne 0 ]] && { echo "Run as root (sudo)."; exit 1; }

# 1. Install ngrok (apt repo where possible, else the static binary).
if ! command -v ngrok >/dev/null 2>&1; then
  say "Installing ngrok…"
  if [[ "$PKG" == "apt" ]]; then
    curl -fsSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
      | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" > /etc/apt/sources.list.d/ngrok.list
    pkg_refresh; pkg_install ngrok || true
  fi
  command -v ngrok >/dev/null 2>&1 || {
    arch="$(uname -m)"; case "$arch" in x86_64) a=amd64;; aarch64) a=arm64;; *) a=amd64;; esac
    curl -fsSL "https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-${a}.tgz" \
      | tar -xz -C /usr/local/bin ngrok
  }
fi
command -v ngrok >/dev/null 2>&1 || { echo "ngrok install failed"; exit 1; }

# 2. Token (asked once; saved to the ngrok config).
[[ -z "$TOKEN" ]] && read -rp "ngrok authtoken (from dashboard.ngrok.com/get-started): " TOKEN
[[ -n "$TOKEN" ]] && ngrok config add-authtoken "$TOKEN" >/dev/null && say "authtoken saved."

# 3. Boot service: forward the HTTPS edge to a public URL.
cat >/etc/systemd/system/satyameba-ngrok.service <<EOF
[Unit]
Description=SATYAMEBA ngrok tunnel (master -> public)
After=network-online.target docker.service
Wants=network-online.target
[Service]
ExecStart=$(command -v ngrok) http https://localhost:443 --host-header=rewrite --log=stdout
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now satyameba-ngrok.service
sleep 3

# 4. Cluster-wide alias so people can fetch the public URL from any node.
cat >/etc/profile.d/satyameba-url.sh <<'EOF'
# Print the SATYAMEBA public URL (set up by setup/ngrok_setup.sh on the master).
satyameba-url() {
  local host="${SAT_MASTER:-localhost}"
  curl -fsS "http://${host}:4040/api/tunnels" 2>/dev/null \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null \
    || echo "ngrok tunnel not up yet"
}
alias satyameba-web='satyameba-url'
EOF
chmod 644 /etc/profile.d/satyameba-url.sh

URL="$(curl -fsS http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || true)"
say "Public URL: ${URL:-<starting… run 'satyameba-url' in a moment>}"
say "On workers, run with SAT_MASTER=<master-ip> so 'satyameba-url' reaches the tunnel API,"
say "or just share the URL above. New shells get the 'satyameba-url' command."
