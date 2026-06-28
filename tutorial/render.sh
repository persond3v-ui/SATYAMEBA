#!/usr/bin/env bash
# ===========================================================================
# Render the SATYAMEBA tutorial scenes to MP4 and place them where the edge
# serves them (frontend/public/tutorial/{user,admin}.mp4). After rendering,
# rebuild the edge image so the videos appear under the in-app "Tutorial" tab.
#
#   ./tutorial/render.sh            # install deps if needed, render, stitch
#   ./tutorial/render.sh l          # quick low-quality preview
#
# Needs manim (Community Edition) + ffmpeg. This script installs them on any
# distro if missing. (Manim's Text needs cairo/pango; ffmpeg stitches + encodes.)
# ===========================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
ROOT="$(cd "$HERE/.." && pwd)"
Q="${1:-h}"   # l | m | h | k
OUT="$ROOT/frontend/public/tutorial"
mkdir -p "$OUT"

# --- deps (cross-distro) ---------------------------------------------------
[[ -f "$ROOT/scripts/lib_pkg.sh" ]] && source "$ROOT/scripts/lib_pkg.sh" && pkg_detect || true
command -v ffmpeg >/dev/null 2>&1 || { echo "[render] installing ffmpeg…"; pkg_install ffmpeg || true; }
command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg is required (could not auto-install). Install it and re-run."; exit 1; }
python3 -c "import manim" 2>/dev/null || { echo "[render] installing manim…"; pip install --quiet "manim>=0.18.0"; }
python3 -c "import manim" 2>/dev/null || { echo "manim is required (pip install manim failed)."; exit 1; }

stitch() {  # stitch <source.py> <out-name>  — concat all of a file's scenes
  local src="$1" name="$2" qdir
  echo "=== rendering $src (-q$Q) ==="
  manim -q"$Q" -a "$src"
  qdir="$(find "media/videos/${src%.py}" -maxdepth 1 -type d 2>/dev/null | sort | tail -n1)"
  [[ -z "$qdir" ]] && { echo "no output for $src"; return 1; }
  : > /tmp/sat_concat.txt
  for f in "$qdir"/*.mp4; do [[ -e "$f" ]] && printf "file '%s'\n" "$f" >> /tmp/sat_concat.txt; done
  ffmpeg -y -f concat -safe 0 -i /tmp/sat_concat.txt -c copy "$OUT/$name.mp4" 2>/dev/null \
    || ffmpeg -y -f concat -safe 0 -i /tmp/sat_concat.txt "$OUT/$name.mp4"
  echo "wrote $OUT/$name.mp4"
}

stitch user_journey.py user
stitch admin_setup.py  admin

echo
echo "Done. Rebuild the edge so the app serves them:"
echo "   docker compose build edge && docker compose up -d edge"
echo "They then appear under the in-app 'Tutorial' tab."
