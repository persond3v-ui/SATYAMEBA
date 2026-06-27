#!/usr/bin/env bash
# Build the SHA256SUMS manifest and cryptographically sign it as the SATYAMEBA
# release, attributing ownership to Samaraho Mukherjee.
#
#   ./scripts/sign_release.sh --key "Samaraho Mukherjee <you@example.com>" [--tag v0.1.0]
#
# Requires a GnuPG secret key. The manifest covers every git-tracked file
# except the signature/manifest themselves and local secrets.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

KEY=""; TAG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --key) KEY="$2"; shift ;;
    --tag) TAG="$2"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac; shift
done

echo "[*] Building SHA256SUMS manifest…"
# List tracked files (fall back to find if not a git repo yet).
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  mapfile -t FILES < <(git ls-files | grep -vE '^(SHA256SUMS|SHA256SUMS\.asc)$')
else
  mapfile -t FILES < <(find . -type f -not -path './.git/*' -not -name 'SHA256SUMS*' \
                       -not -path './secrets/*' -not -name '.env' | sed 's|^\./||')
fi
: > SHA256SUMS
for f in "${FILES[@]}"; do
  sha256sum "$f" >> SHA256SUMS
done
echo "[+] $(wc -l < SHA256SUMS) files hashed into SHA256SUMS"

if [[ -n "$KEY" ]]; then
  echo "[*] Signing manifest with GPG key: $KEY"
  gpg --batch --yes --local-user "$KEY" --armor --detach-sign --output SHA256SUMS.asc SHA256SUMS
  echo "[+] Wrote SHA256SUMS.asc (detached signature)"
else
  echo "[!] No --key given: manifest built but NOT signed."
  echo "    Re-run with --key \"Samaraho Mukherjee <you@example.com>\" to bind ownership."
fi

if [[ -n "$TAG" ]]; then
  echo "[*] Creating signed git tag $TAG"
  if [[ -n "$KEY" ]]; then
    git tag -s "$TAG" -u "$KEY" -m "SATYAMEBA $TAG — signed by Samaraho Mukherjee"
  else
    git tag -a "$TAG" -m "SATYAMEBA $TAG"
  fi
  echo "[+] Tag $TAG created (push with: git push origin $TAG)"
fi
echo "[✓] Done."
