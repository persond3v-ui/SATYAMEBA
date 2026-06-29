#!/usr/bin/env bash
# Restore a SATYAMEBA backup created by backup.sh.
#   ./scripts/restore.sh backups/satyameba-YYYYMMDD-HHMMSS
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

DIR="${1:-}"
[[ -d "$DIR" && -f "$DIR/db.sql.gz" ]] || { echo "usage: $0 <backup-dir with db.sql.gz>"; exit 1; }
[[ -f .env ]] || { echo "no .env — restore env.bak first: cp $DIR/env.bak .env"; exit 1; }
source "$ROOT/scripts/load_env.sh"; load_env "$ROOT/.env"

CID="$(docker ps --format '{{.ID}} {{.Image}}' | awk '/postgres/ {print $1; exit}')"
[[ -z "$CID" ]] && { echo "Postgres container not found."; exit 1; }

read -r -p "This will overwrite data in '$POSTGRES_DB'. Continue? [y/N] " ok
[[ "$ok" == "y" || "$ok" == "Y" ]] || { echo "aborted"; exit 1; }

echo "[*] Restoring database…"
gunzip -c "$DIR/db.sql.gz" | docker exec -i "$CID" psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
echo "[✓] Restored from $DIR. Restart the stack so services pick up clean state."
