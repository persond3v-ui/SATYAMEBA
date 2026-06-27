#!/usr/bin/env bash
# Back up SATYAMEBA: Postgres dump + secrets/env needed to restore.
#   ./scripts/backup.sh [--dir backups]
# Writes a timestamped folder. Works for both the compose and swarm db container.
# NOTE: the archive contains .env and signing keys — store it somewhere safe.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

BASE="backups"
[[ "${1:-}" == "--dir" ]] && BASE="$2"
[[ -f .env ]] || { echo "no .env found"; exit 1; }
set -a; source .env; set +a

CID="$(docker ps --filter 'ancestor=postgres:16-alpine' -q | head -1)"
[[ -z "$CID" ]] && { echo "Postgres container not found (external DB? dump it directly)."; exit 1; }

OUT="$BASE/satyameba-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "[*] Dumping database…"
docker exec "$CID" pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$OUT/db.sql.gz"
cp .env "$OUT/env.bak"
[[ -d secrets ]] && cp -r secrets "$OUT/secrets"
chmod -R go-rwx "$OUT"
echo "[✓] Backup written to $OUT ($(du -sh "$OUT" | cut -f1))"
echo "    Restore with: ./scripts/restore.sh $OUT"
