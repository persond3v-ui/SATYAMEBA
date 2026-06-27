#!/usr/bin/env bash
# Render all SATYAMEBA tutorial scenes to video.
#   ./tutorial/render.sh        # high quality (-qh)
#   ./tutorial/render.sh l      # quick low-quality preview
#   ./tutorial/render.sh k      # 4K
set -euo pipefail
cd "$(dirname "$0")"
Q="${1:-h}"   # l | m | h | k
command -v manim >/dev/null || { echo "manim not found — pip install -r requirements.txt"; exit 1; }

for f in admin_setup.py user_journey.py; do
  echo "=== rendering $f (quality -q$Q) ==="
  manim -q"$Q" -a "$f"          # -a renders every Scene in the file
done
echo
echo "Done. Videos are under tutorial/media/videos/<file>/<res>/"
echo "Tip: stitch a file's scenes into one mp4 with the helper at the bottom of README.md"
