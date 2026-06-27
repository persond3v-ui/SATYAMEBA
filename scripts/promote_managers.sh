#!/usr/bin/env bash
# Promote worker nodes to Swarm managers for quorum HA. Run on a manager.
#   ./scripts/promote_managers.sh worker2 worker3
# Use an ODD number of managers (3 or 5) so the cluster keeps quorum if one dies.
set -euo pipefail
[[ $# -lt 1 ]] && { echo "usage: $0 <node-hostname> [node-hostname...]"; exit 1; }
docker node promote "$@"
echo "Promoted: $*"
docker node ls
N=$(docker node ls --filter role=manager -q | wc -l)
echo "Managers now: $N  (odd numbers — 3 or 5 — are recommended for quorum)."
