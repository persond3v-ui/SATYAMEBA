#!/usr/bin/env bash
# Back up SATYAMEBA: Postgres dump (+ optionally secrets/env needed to restore).
#   ./scripts/backup.sh [--dir backups] [--no-secrets]
# Writes a timestamped folder. Works for both the compose and swarm db container
# (matches any postgres image tag). By default the archive ALSO contains .env and
# signing keys — store it securely, or pass --no-secrets to omit them.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

BASE="backups"; INCLUDE_SECRETS=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir) BASE="$2"; shift ;;
    --no-secrets) INCLUDE_SECRETS=0 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
[[ -f .env ]] || { echo "no .env found"; exit 1; }
source "$ROOT/scripts/load_env.sh"; load_env "$ROOT/.env"

# Find the Postgres container by image family (any tag), not an exact tag.
CID="$(docker ps --format '{{.ID}} {{.Image}}' | awk '/postgres/ {print $1; exit}')"
[[ -z "$CID" ]] && { echo "Postgres container not found (external DB? dump it directly)."; exit 1; }

OUT="$BASE/satyameba-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "[*] Dumping database from container ${CID}…"
docker exec "$CID" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT/db.sql.gz"
if [[ $INCLUDE_SECRETS -eq 1 ]]; then
  cp .env "$OUT/env.bak"
  [[ -d secrets ]] && cp -r secrets "$OUT/secrets"
  echo "[!] Archive includes .env + signing keys — store it securely."
else
  echo "[i] --no-secrets: database only (you must restore .env/secrets separately)."
fi
chmod -R go-rwx "$OUT"
echo "[✓] Backup written to $OUT ($(du -sh "$OUT" | cut -f1))"
echo "    Restore with: ./scripts/restore.sh $OUT"
