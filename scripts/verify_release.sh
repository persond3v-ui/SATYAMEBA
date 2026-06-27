#!/usr/bin/env bash
# Verify the SATYAMEBA integrity manifest (and signature, if present).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$ROOT"

[[ -f SHA256SUMS ]] || { echo "SHA256SUMS not found. Run sign_release.sh first."; exit 1; }

echo "[*] Verifying file digests…"
if sha256sum -c SHA256SUMS --quiet; then
  echo "[+] All files match the manifest — integrity OK."
else
  echo "[!] One or more files differ from the manifest."; exit 1
fi

if [[ -f SHA256SUMS.asc ]]; then
  echo "[*] Verifying owner signature…"
  if gpg --verify SHA256SUMS.asc SHA256SUMS; then
    echo "[+] Signature valid — ownership attributed to Samaraho Mukherjee."
  else
    echo "[!] Signature verification FAILED."; exit 1
  fi
else
  echo "[i] No SHA256SUMS.asc present (manifest is unsigned)."
fi
echo "[✓] Verification complete."
