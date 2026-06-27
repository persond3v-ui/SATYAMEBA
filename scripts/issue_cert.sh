#!/usr/bin/env bash
# Issue a real TLS certificate for the edge via Let's Encrypt (webroot), using
# the /.well-known/acme-challenge/ path already wired into the edge nginx config.
#
#   sudo ./scripts/issue_cert.sh --domain notebooks.mylab.edu --email you@lab.edu
#
# Falls back gracefully if certbot is missing (prints install hint). After
# issuing, it copies the cert into secrets/certs/ and restarts the edge.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

DOMAIN=""; EMAIL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift ;;
    --email) EMAIL="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
[[ -z "$DOMAIN" || -z "$EMAIL" ]] && { echo "usage: $0 --domain D --email E"; exit 1; }

if ! command -v certbot >/dev/null 2>&1; then
  echo "certbot not found. Install: sudo apt-get install -y certbot"; exit 1
fi

mkdir -p var/www/certbot
certbot certonly --webroot -w "$ROOT/var/www/certbot" \
  -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive

LE="/etc/letsencrypt/live/$DOMAIN"
cp "$LE/fullchain.pem" secrets/certs/satyameba.crt
cp "$LE/privkey.pem"   secrets/certs/satyameba.key
chmod 600 secrets/certs/satyameba.key
echo "[+] Installed cert for $DOMAIN. Reloading edge…"
docker compose restart edge 2>/dev/null || docker service update --force satyameba_edge 2>/dev/null || true
echo "[✓] Done. Add a cron/systemd timer for 'certbot renew' + this copy step."
