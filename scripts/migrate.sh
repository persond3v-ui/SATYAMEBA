#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — database migration helper (Alembic).
#
# You normally never need this: the gateway auto-migrates at startup. Use it for
# manual control — inspecting history, or rolling back.
#
#   ./scripts/migrate.sh                 # upgrade to head (same as startup)
#   ./scripts/migrate.sh current         # what revision is the DB on?
#   ./scripts/migrate.sh history         # list migrations
#   ./scripts/migrate.sh downgrade -1    # roll back one revision
#   ./scripts/migrate.sh revision --autogenerate -m "add column"   # create one
#
# Runs inside the gateway container when the stack is up (so it uses the live
# Postgres + env), otherwise locally against the URL in .env.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="${1:-upgrade}"; shift || true
ARGS=("$@")
[[ "$CMD" == "upgrade"   && ${#ARGS[@]} -eq 0 ]] && ARGS=("head")
[[ "$CMD" == "downgrade" && ${#ARGS[@]} -eq 0 ]] && ARGS=("-1")

COMPOSE="docker compose -f $ROOT/docker-compose.yml"
if $COMPOSE ps gateway 2>/dev/null | grep -qiE "up|running"; then
  echo "[migrate] in the gateway container…"
  $COMPOSE exec -T gateway alembic "$CMD" "${ARGS[@]}"
else
  echo "[migrate] locally (gateway/)…"
  cd "$ROOT/gateway"
  source "$ROOT/scripts/load_env.sh"; load_env "$ROOT/.env"
  alembic "$CMD" "${ARGS[@]}"
fi
