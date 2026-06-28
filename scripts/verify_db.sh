#!/usr/bin/env bash
# ===========================================================================
# Verify SATYAMEBA's database path — works for the bundled DB, the PgBouncer
# pooler, or the HA (pgpool + repmgr) overlay.
#
#   ./scripts/verify_db.sh
#
# Checks: the gateway can actually reach + query the database via its configured
# SAT_DATABASE_URL; the pooler is up (if deployed); and, on the HA overlay, both
# Postgres nodes are visible to pgpool with one primary.
# ===========================================================================
set -uo pipefail
PASS=0; FAIL=0
ok()   { printf "  \033[1;32mPASS\033[0m %s\n" "$1"; PASS=$((PASS+1)); }
bad()  { printf "  \033[1;31mFAIL\033[0m %s\n" "$1"; FAIL=$((FAIL+1)); }
info() { printf "\033[1;36m[verify-db]\033[0m %s\n" "$1"; }

GW="$(docker ps --filter 'name=gateway' --format '{{.ID}}' 2>/dev/null | head -n1)"
[[ -z "$GW" ]] && { echo "gateway container not running — start the stack first."; exit 1; }

info "1. Gateway → database connectivity (via SAT_DATABASE_URL)"
if docker exec -i "$GW" python -c "
from sqlalchemy import text
from app.database import engine
with engine.connect() as c:
    assert c.execute(text('select 1')).scalar_one() == 1
    rec = c.execute(text('select pg_is_in_recovery()')).scalar_one() if engine.dialect.name=='postgresql' else False
    print('primary' if not rec else 'standby')
" 2>/dev/null; then ok "gateway queried the DB"
else bad "gateway cannot reach/query the DB — check SAT_DATABASE_URL + the DB service"; fi

info "2. Connection pooler"
if docker ps --format '{{.Names}}' | grep -qi pgbouncer; then ok "PgBouncer running"
elif docker ps --format '{{.Names}}' | grep -qi pgpool; then ok "pgpool running (HA endpoint)"
else info "  no pooler deployed (optional — add docker-compose.pgbouncer.yml)"; fi

info "3. HA replication status (only on the HA overlay)"
PP="$(docker ps --filter 'name=pgpool' --format '{{.ID}}' 2>/dev/null | head -n1)"
if [[ -n "$PP" ]]; then
  if docker exec -i "$PP" bash -lc 'PGPASSWORD="$PGPOOL_POSTGRES_PASSWORD" psql -h localhost -p 5432 -U "$PGPOOL_POSTGRES_USERNAME" -d postgres -tAc "show pool_nodes;"' 2>/dev/null | grep -q "primary"; then
    ok "pgpool sees a primary backend"
    docker exec -i "$PP" bash -lc 'PGPASSWORD="$PGPOOL_POSTGRES_PASSWORD" psql -h localhost -p 5432 -U "$PGPOOL_POSTGRES_USERNAME" -d postgres -c "show pool_nodes;"' 2>/dev/null | sed 's/^/    /'
  else bad "pgpool cannot see a healthy primary — check the repmgr nodes"; fi
else info "  not an HA deployment (single DB) — DB is a SPOF; see DEPLOYMENT §11."; fi

echo
info "Result: ${PASS} passed, ${FAIL} failed."
[[ "$FAIL" -eq 0 ]] && exit 0 || exit 1
