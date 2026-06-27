#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — scan host resources and size the deployment to them.
#
#   ./scripts/scan_resources.sh [--users N] [--reserve-pct 80]
#
# Scans the ENTIRE available storage (on the Docker data root), plus RAM and CPU,
# and writes computed allocations into .env so notebooks use what the machine
# actually has instead of fixed guesses:
#   SAT_TOTAL_STORAGE_GB, SAT_FREE_STORAGE_GB  — what was found
#   SAT_USER_STORAGE_LIMIT_GB                  — per-user share of free storage
#   SAT_MEM_LIMIT, SAT_CPU_LIMIT               — per-notebook (medium profile)
#   SAT_EXPECTED_USERS                         — planning denominator
# Idempotent; re-run after adding disks/RAM. Pair with --reserve-pct to leave
# head-room for the OS and the platform itself.
# ===========================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

USERS=8
RESERVE_PCT=80
while [[ $# -gt 0 ]]; do
  case "$1" in
    --users) USERS="$2"; shift ;;
    --reserve-pct) RESERVE_PCT="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done
[[ "$USERS" -lt 1 ]] && USERS=1

# Docker data root (where images/volumes live); fall back to /var/lib/docker, /.
DROOT="/var/lib/docker"
if command -v docker >/dev/null 2>&1; then
  DROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
fi
[[ -d "$DROOT" ]] || DROOT="/"

# Storage on that filesystem (GiB).
read -r TOTAL_GB FREE_GB < <(df -BG --output=size,avail "$DROOT" 2>/dev/null | tail -1 | tr -dc '0-9 \n' | awk '{print $1, $2}')
TOTAL_GB=${TOTAL_GB:-0}; FREE_GB=${FREE_GB:-0}

# RAM (GiB) and CPU cores.
RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 4)
CORES=$(nproc 2>/dev/null || echo 2)

# Allocations.
USABLE_FREE=$(( FREE_GB * RESERVE_PCT / 100 ))
PER_USER_GB=$(( USABLE_FREE / USERS )); [[ "$PER_USER_GB" -lt 1 ]] && PER_USER_GB=1
PER_USER_MEM_GB=$(( RAM_GB * 60 / 100 / USERS )); [[ "$PER_USER_MEM_GB" -lt 2 ]] && PER_USER_MEM_GB=2
# CPU per user, one decimal, min 1.
PER_USER_CPU=$(awk -v c="$CORES" -v u="$USERS" 'BEGIN{v=c*0.7/u; if(v<1)v=1; printf "%.1f", v}')

set_env() {  # set_env KEY VALUE  — replace or append in .env
  local k="$1" v="$2"
  if grep -q "^${k}=" .env 2>/dev/null; then
    sed -i "s|^${k}=.*|${k}=${v}|" .env
  else
    echo "${k}=${v}" >> .env
  fi
}

[[ -f .env ]] || { echo "[!] .env not found — run scripts/gen_secrets.sh first."; exit 1; }
set_env SAT_TOTAL_STORAGE_GB "$TOTAL_GB"
set_env SAT_FREE_STORAGE_GB "$FREE_GB"
set_env SAT_USER_STORAGE_LIMIT_GB "$PER_USER_GB"
set_env SAT_EXPECTED_USERS "$USERS"
set_env SAT_MEM_LIMIT "${PER_USER_MEM_GB}G"
set_env SAT_CPU_LIMIT "$PER_USER_CPU"

cat <<EOF
[satyameba] resource scan @ ${DROOT}
  storage : ${TOTAL_GB} GiB total, ${FREE_GB} GiB free  (reserve ${RESERVE_PCT}%)
  memory  : ${RAM_GB} GiB
  cpu     : ${CORES} cores
  planning for ${USERS} concurrent users:
    per-user storage : ${PER_USER_GB} GiB
    per-notebook RAM : ${PER_USER_MEM_GB} GiB   (medium profile)
    per-notebook CPU : ${PER_USER_CPU} cores
  -> written to .env
EOF
