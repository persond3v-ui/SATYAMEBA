#!/usr/bin/env bash
# ===========================================================================
# Expose SATYAMEBA on YOUR domain over real HTTPS — via Cloudflare Tunnel.
# No public IP, no router/port-forwarding. Failsafe + idempotent.
#
#   sudo ./setup/public_domain.sh
#   sudo ./setup/public_domain.sh --token <TUNNEL_TOKEN> [--hostname notebooks.you.com] [--harden]
#
# TWO MODES:
#   • token  (recommended — one prompt): create a tunnel in the Cloudflare
#     dashboard (Zero Trust → Networks → Tunnels), copy its TOKEN, paste it here.
#     We install it as a boot service. In the dashboard, set the public hostname
#     → service  https://localhost:443  with "No TLS Verify" ON (our edge cert
#     is self-signed). Cloudflare then serves your domain with a trusted cert.
#   • login  (blank token): browser login, then we create the tunnel, route DNS
#     to your hostname, write the config and install the service — fully scripted.
#
# --harden flips the stack to a public-safe posture (production mode + admin 2FA
# + adds your hostname to CORS) and redeploys.
# ===========================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"
source "$ROOT/scripts/lib_pkg.sh"
say()  { printf "\033[1;35m[public]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[public]\033[0m %s\n" "$*"; }
pkg_detect || true

TOKEN=""; HOSTNAME=""; HARDEN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="${2:-}"; shift ;;
    --hostname) HOSTNAME="${2:-}"; shift ;;
    --harden) HARDEN=1 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
[[ $EUID -ne 0 ]] && { echo "Run as root (sudo)."; exit 1; }

# --- 1. install cloudflared (static binary = most portable) -------------------
if ! command -v cloudflared >/dev/null 2>&1; then
  say "Installing cloudflared…"
  case "$(uname -m)" in x86_64) A=amd64;; aarch64|arm64) A=arm64;; armv7l) A=arm;; *) A=amd64;; esac
  if curl -fsSL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${A}" \
       -o /usr/local/bin/cloudflared 2>/dev/null; then
    chmod +x /usr/local/bin/cloudflared
  else
    pkg_install cloudflared || true
  fi
fi
command -v cloudflared >/dev/null 2>&1 || { echo "cloudflared install failed — install it manually and re-run."; exit 1; }
say "cloudflared: $(cloudflared --version 2>&1 | head -n1)"

# --- 2. prompt for mode -------------------------------------------------------
if [[ -z "$TOKEN" ]]; then
  echo
  echo "Paste your Cloudflare Tunnel TOKEN (Zero Trust → Networks → Tunnels →"
  echo "create a tunnel → 'Install connector' shows a token), or leave blank to"
  echo "do an interactive browser login instead."
  read -rs -p "Tunnel token (blank = browser login): " TOKEN; echo
fi

if [[ -n "$TOKEN" ]]; then
  # --- token mode (remotely-managed; simplest + most failsafe) ----------------
  say "Installing the tunnel as a boot service (token mode)…"
  cloudflared service install "$TOKEN" 2>&1 | tee -a /dev/null || warn "service install returned non-zero (may already exist)"
  systemctl enable --now cloudflared 2>/dev/null || true
  say "Tunnel service installed."
  warn "FINISH IN THE DASHBOARD: set the public hostname (your domain) → service"
  warn "  https://localhost:443  with 'No TLS Verify' = ON. Then it's live over HTTPS."
else
  # --- login mode (locally-managed; fully scripts DNS too) --------------------
  [[ -z "$HOSTNAME" ]] && read -rp "Public hostname for the site (e.g. notebooks.yourdomain.com): " HOSTNAME
  [[ -z "$HOSTNAME" ]] && { echo "A hostname is required for login mode."; exit 1; }
  say "Opening browser login (authorize your domain)…"
  cloudflared tunnel login || { echo "login failed"; exit 1; }
  cloudflared tunnel create satyameba 2>/dev/null || say "tunnel 'satyameba' already exists (reusing)."
  TID="$(cloudflared tunnel list 2>/dev/null | awk '/satyameba/{print $1; exit}')"
  [[ -z "$TID" ]] && { echo "could not determine tunnel id"; exit 1; }
  say "Routing DNS $HOSTNAME → tunnel $TID …"
  cloudflared tunnel route dns satyameba "$HOSTNAME" || warn "DNS route may already exist."
  mkdir -p /etc/cloudflared
  cred="$(ls -1 "$HOME"/.cloudflared/"$TID".json 2>/dev/null | head -n1)"
  cat >/etc/cloudflared/config.yml <<EOF
tunnel: ${TID}
credentials-file: ${cred:-/root/.cloudflared/${TID}.json}
ingress:
  - hostname: ${HOSTNAME}
    service: https://localhost:443
    originRequest:
      noTLSVerify: true
  - service: http_status:404
EOF
  [[ -n "$cred" ]] && cp "$cred" "/etc/cloudflared/$(basename "$cred")" 2>/dev/null || true
  cloudflared service install 2>/dev/null || true
  systemctl enable --now cloudflared 2>/dev/null || true
  say "Tunnel live: https://${HOSTNAME}/"
fi

# --- 3. optional: harden the stack for public exposure ------------------------
if [[ $HARDEN -eq 0 ]] && [[ -t 0 ]]; then
  read -rp "Harden the stack for public exposure (production mode + admin 2FA)? [Y/n] " a
  [[ ! "$a" =~ ^[Nn]$ ]] && HARDEN=1
fi
if [[ $HARDEN -eq 1 && -f "$ROOT/.env" ]]; then
  say "Hardening for public exposure…"
  bash "$ROOT/scripts/set_env.sh" SAT_ENVIRONMENT production "$ROOT/.env"
  bash "$ROOT/scripts/set_env.sh" SAT_REQUIRE_ADMIN_2FA true "$ROOT/.env"
  if [[ -n "$HOSTNAME" ]]; then
    cur="$(grep '^SAT_CORS_ORIGINS=' "$ROOT/.env" | cut -d= -f2-)"
    case "$cur" in *"$HOSTNAME"*) : ;; *) bash "$ROOT/scripts/set_env.sh" SAT_CORS_ORIGINS "${cur:+$cur,}https://$HOSTNAME" "$ROOT/.env" ;; esac
  fi
  say "Redeploying with the hardened settings…"
  if docker info 2>/dev/null | grep -q "Swarm: active"; then
    ( set -a; . "$ROOT/.env"; set +a; docker stack deploy -c "$ROOT/docker-compose.swarm.yml" satyameba ) || warn "redeploy had warnings"
  else
    ( set -a; . "$ROOT/.env"; set +a; docker compose -f "$ROOT/docker-compose.yml" up -d ) || warn "redeploy had warnings"
  fi
  warn "Production mode is ON: API docs are disabled and the gateway fails closed"
  warn "if secrets are weak. Admins must now enrol TOTP 2FA. Consider Cloudflare"
  warn "Access (Zero Trust) in front for an SSO gate, and gVisor for untrusted users."
fi
say "Done. Your site is reachable on your domain over HTTPS via Cloudflare Tunnel."
