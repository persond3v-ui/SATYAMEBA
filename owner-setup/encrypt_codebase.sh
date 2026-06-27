#!/usr/bin/env bash
# ===========================================================================
# SATYAMEBA — owner-only codebase confidentiality.   Owner: Samaraho Mukherjee.
#
# Encrypts the source AT REST so the git host, backups, and casual disk access
# can't read it without YOUR key — and (optionally) ships only BUILT IMAGES to
# workers so no source lands on them.
#
#   ./owner-setup/encrypt_codebase.sh init        # set up git-crypt with your key
#   ./owner-setup/encrypt_codebase.sh images      # build+save images for workers
#
# HONEST LIMIT: code that RUNS on a node must be decrypted to execute, so anyone
# with root on that node can read the running code. This protects the repo/host/
# backups, not the live process. (Same truth as 'encrypted JS'.)
# ===========================================================================
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"
CMD="${1:-help}"

case "$CMD" in
  init)
    command -v git-crypt >/dev/null || { echo "Install git-crypt: sudo apt-get install -y git-crypt"; exit 1; }
    command -v gpg >/dev/null || { echo "Install gnupg and create a key (gpg --gen-key)."; exit 1; }
    [[ -d .git ]] || { echo "Run inside the git repo."; exit 1; }
    git-crypt init 2>/dev/null || echo "git-crypt already initialised"
    cat > .gitattributes <<'EOF'
# Owner-only encrypted source (git-crypt). The git host stores ciphertext;
# only keys added via `git-crypt add-gpg-user` can decrypt.
gateway/** filter=git-crypt diff=git-crypt
frontend/src/** filter=git-crypt diff=git-crypt
jupyterhub/** filter=git-crypt diff=git-crypt
owner-setup/** filter=git-crypt diff=git-crypt
docker-compose*.yml filter=git-crypt diff=git-crypt
# (Docs, diagrams, README stay readable so the repo is still presentable.)
EOF
    echo "[+] .gitattributes written. Add your key:"
    echo "      git-crypt add-gpg-user 'Samaraho Mukherjee <you@example.com>'"
    echo "    Then commit. Anyone cloning without your key sees encrypted blobs."
    echo "    Unlock on a trusted machine with:  git-crypt unlock"
    ;;
  images)
    echo "[*] Building images on this (owner) machine…"
    docker compose build
    docker compose --profile build build notebook-image
    mkdir -p dist-images
    for img in gateway jupyterhub edge notebook; do
      docker save "satyameba/${img}:latest" | gzip > "dist-images/${img}.tar.gz"
      echo "  saved dist-images/${img}.tar.gz"
    done
    echo "[+] Ship dist-images/*.tar.gz to workers and 'docker load' them."
    echo "    Workers then run WITHOUT any source checkout."
    ;;
  *)
    grep '^#' "$0" | sed 's/^# \{0,1\}//' | head -20 ;;
esac
