#!/usr/bin/env bash
# ===========================================================================
# Reclaim disk + tidy leftovers after users finish their jobs. Safe to run on a
# timer (a systemd timer is installed by install_services.sh).
#
#   ./scripts/cleanup.sh           # safe: stopped notebooks, dangling images,
#                                  # build cache, unused ANONYMOUS volumes
#   ./scripts/cleanup.sh --deep    # also clears shared scratch (/shared/tmp, *.tmp)
#
# NEVER touches a user's /work data or their named per-user volume — only the
# transient mess (stopped containers, dangling layers, scratch files).
# ===========================================================================
set -uo pipefail
say() { printf "\033[1;36m[cleanup]\033[0m %s\n" "$*"; }
DEEP=0; [[ "${1:-}" == "--deep" ]] && DEEP=1
command -v docker >/dev/null 2>&1 || { echo "docker not found"; exit 1; }

say "Removing stopped notebook containers…"
docker ps -aq --filter "label=satyameba.sid" --filter "status=exited"  | xargs -r docker rm -f 2>/dev/null || true
docker ps -aq --filter "label=satyameba.sid" --filter "status=dead"    | xargs -r docker rm -f 2>/dev/null || true

say "Pruning dangling images + build cache…"
docker image   prune -f       >/dev/null 2>&1 || true
docker builder prune -f       >/dev/null 2>&1 || true

say "Pruning unused ANONYMOUS volumes (named per-user volumes are kept)…"
docker volume  prune -f       >/dev/null 2>&1 || true

if [[ $DEEP -eq 1 ]]; then
  say "Deep: clearing shared scratch…"
  SHARED="${SAT_SHARED_HOST_PATH:-/srv/satyameba/shared}"
  find "$SHARED" -maxdepth 3 -name '*.tmp' -mtime +1 -delete 2>/dev/null || true
  rm -rf "$SHARED"/tmp/* "$SHARED"/.ipynb_checkpoints 2>/dev/null || true
fi

ROOTDIR="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || echo /var/lib/docker)"
say "Disk on the Docker data root:"; df -h "$ROOTDIR" 2>/dev/null | tail -1
say "Done."
