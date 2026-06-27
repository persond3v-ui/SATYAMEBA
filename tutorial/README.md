# SATYAMEBA — Animated Tutorials (Manim)

Two narrated, step-by-step animations built with **Manim Community Edition**:

| File | Audience | Scenes |
|------|----------|--------|
| `admin_setup.py` | **Admins / developers** standing the cluster up on 4 nodes | AdminIntro · Architecture · Step1Wizard · Step2Master · Step3Workers · Step4Dashboard · Step5Security · AdminOutro |
| `user_journey.py` | **End users** running notebooks | UserIntro · Register · Launch · Workspace · Persistence · UserSecurity · UserOutro |

The narrative these animate is in [`NARRATIVE.md`](NARRATIVE.md). Custom SVG art
lives in `assets/`. The scenes are **LaTeX-free** (they use `Text`, not `Tex`),
so you only need ffmpeg + manim.

## Install

```bash
# Debian/Ubuntu system deps
sudo apt-get update && sudo apt-get install -y ffmpeg python3-pip libcairo2 libpango-1.0-0

# Python deps (a venv is recommended)
pip install -r tutorial/requirements.txt
```

(See the Manim docs if your distro needs extra cairo/pango packages.)

## Render

```bash
./tutorial/render.sh           # high quality, both files, every scene
./tutorial/render.sh l         # fast low-res preview while iterating
```

Or drive manim directly:

```bash
manim -qh tutorial/admin_setup.py                 # all scenes in the file
manim -qh tutorial/admin_setup.py Architecture    # a single scene
manim -ql -p tutorial/user_journey.py Launch      # quick preview + auto-play
```

Quality flags: `-ql` (480p) · `-qm` (720p) · `-qh` (1080p) · `-qk` (4K).
Outputs land in `tutorial/media/videos/<file>/<res>/`.

## Stitch a file's scenes into one video (optional)

`-a` renders each scene to its own mp4. To concatenate them in order:

```bash
cd tutorial/media/videos/admin_setup/1080p60
printf "file '%s'\n" AdminIntro.mp4 Architecture.mp4 Step1Wizard.mp4 \
  Step2Master.mp4 Step3Workers.mp4 Step4Dashboard.mp4 Step5Security.mp4 \
  AdminOutro.mp4 > list.txt
ffmpeg -f concat -safe 0 -i list.txt -c copy SATYAMEBA-admin-setup.mp4
```

## Customising

- Colours and helper mobjects live in `theme.py` (they mirror the web app).
- Swap or restyle icons by editing the SVGs in `assets/`.
- Each scene is independent — tweak one without touching the others.
