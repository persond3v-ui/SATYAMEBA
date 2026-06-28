# SATYAMEBA — Deployment Guide

## 0. Prerequisites (handled by the setup wizard)

On **every** Debian box:

```bash
sudo apt-get update && sudo apt-get install -y python3-tk   # for the GUI
sudo python3 setup/satyameba_setup.py
```

In the wizard: **Check dependencies → Install/fix missing → Verify GPU**. It
installs Docker CE, Docker Compose v2, the NVIDIA Container Toolkit, and friends,
then confirms `docker run --gpus all … nvidia-smi` works.

> RTX 5070 note: it is a very recent GPU. If `nvidia-smi` shows nothing after
> install, the Debian-stable driver is too old — install a 555+ driver from
> NVIDIA's CUDA apt repo, reboot, and re-run **Verify GPU**.

## 0.5 All-in-one installer wizard (recommended)

The flagship one-shot installer collects your settings in input fields, then runs
**the whole pipeline in order with a live progress bar**, like a normal setup
program:

```bash
sudo ./setup/install_wizard.sh
```

Order: dependencies → NVIDIA driver/toolkit → backend (secrets, resource scan,
build images, bring-up) → boot services → optional desktop-slim + console TUI →
verify → **owner break-glass** (ownership / Tailscale / tamper watchdog, run last
because Tailscale login is interactive). Each step is an existing, tested script;
everything is logged; a failure stops with a clear message and is idempotent to
re-run. Flags: `--unattended` (defaults/env, no prompts), `--dry-run` (preview,
change nothing), `--verbose` (stream output instead of the bar).

It uses `dialog` → `whiptail` → plain prompts, works at **any resolution**, on any
distro (apt/dnf/yum/pacman/zypper/apk). `setup/wizard.sh` remains as a lighter
menu for one-off actions (join a worker, slim the desktop, etc.).

## 1. Single machine (quickest)

```bash
sudo python3 setup/satyameba_setup.py     # role: Master, tick "Single-host" (desktop GUI)
sudo ./setup/wizard.sh                     # or the TUI wizard → "Single host"
./setup/master_init.sh --single --gpu      # or fully headless
```
Open `https://localhost/`. The admin credentials are in the generated `.env`.

## 2. The 4-desktop lab (Swarm)

### One command for the whole cluster (recommended)

From the master, the one-time wizard sets up **every** PC end to end:

```bash
sudo ./setup/cluster_setup.sh
```

It runs as the **super user** (re-execs via `sudo`; escalates to a real root
shell where Debian's `sudo` misbehaves), asks **once** for your root/SSH password
(passed via `sshpass -e`, never shown in `ps`) and uses it to act as root on
every node, installs **Docker + the NVIDIA toolkit** where missing, **scans each
GPU and cross-checks one CUDA/torch wheel** so a node that isn't an RTX 5070
still integrates, sets up the **un-removable owner + break-glass** on all PCs,
joins the Swarm, turns on **NFS + at-rest encryption** if you choose, and hosts
the site on **ports 80 & 443 only**. Every step is verified and logged; it's
idempotent, so a re-run is safe. (Prefer the manual steps below for fine control.)

### On the master (manual)

```bash
./setup/master_init.sh --advertise-addr 192.168.1.10 --domain satyameba.local
```
It prints a ready-to-paste worker command containing the swarm join-token, the
node secret, and the gateway URL.

### On each worker

```bash
sudo ./setup/worker_join.sh \
    --master-ip 192.168.1.10 \
    --join-token SWMTKN-1-xxxx \
    --node-secret <node-secret> \
    --gateway https://192.168.1.10 \
    --gpu --master-ssh user@192.168.1.10
```

This joins the swarm, builds the notebook sandbox image locally, registers the
node (it appears under **Admin → Nodes**), installs a heartbeat timer, and—if
`--gpu`—labels the node so GPU notebooks land on it.

Re-deploy/refresh the stack any time from the master:

```bash
set -a; source .env; set +a
docker stack deploy -c docker-compose.swarm.yml satyameba
```

## 3. Networking / firewall

Open **to the VLAN only** (not the internet):
* `2377/tcp` — swarm management
* `7946/tcp+udp` — node discovery
* `4789/udp` — overlay traffic

Open to clients: `80`, `443` on the master only.

```bash
# example, master:
sudo ufw allow from 192.168.1.0/24 to any port 2377,7946,4789 proto any
sudo ufw allow 80,443/tcp
```

## 4. Sudoers / docker group

So operators run `docker` without `sudo`, the wizard offers **“Add me to docker
group”** (`usermod -aG docker $USER`; re-login required). If you prefer scoped
passwordless sudo for the bootstrap scripts instead:

```
# /etc/sudoers.d/satyameba  (visudo)
%satyameba ALL=(root) NOPASSWD: /usr/bin/docker, /path/to/SATYAMEBA/setup/worker_join.sh
```

## 5. GPU scheduling

* Workers with `--gpu` get the swarm label `satyameba.gpu=true`.
* With `SAT_GPU_ENABLED=true`, SwarmSpawner constrains GPU notebooks to those
  nodes and reserves a GPU generic resource.
* DCGM exporter runs only on GPU nodes; GPU panels populate in Grafana.

## 6. Optional: stronger sandbox

Run notebooks under gVisor for defense-in-depth against container escape:

```bash
# install runsc, then on each worker's /etc/docker/daemon.json add a runtime,
# and set the spawner to use it (DockerSpawner.extra_host_config.runtime = "runsc").
```

## 7. Backups

* `pgdata` volume — the user/audit database (back this up).
* `hubdata` volume — Hub state.
* Per-user notebook volumes — `satyameba-user-<username>`.

## 8. TLS for production

Self-signed is the default. For a real certificate:

```bash
sudo ./scripts/issue_cert.sh --domain notebooks.mylab.edu --email you@lab.edu
```

This uses the ACME http-01 webroot already wired into the edge, copies the cert
into `secrets/certs/`, and reloads the edge. Add a timer for `certbot renew`.

## 9. Storage-aware sizing

`scripts/scan_resources.sh` is run automatically by `master_init.sh`, or on
demand:

```bash
./scripts/scan_resources.sh --users 16        # plan for 16 concurrent users
```

It scans total/free disk (Docker data root), RAM and CPU, and writes
per-notebook RAM/CPU plus a per-user storage share into `.env`. For a **hard**
per-user disk quota set `SAT_STORAGE_QUOTA_ENFORCE=true` — this needs an XFS
prjquota-enabled Docker storage driver; otherwise the limit is advisory.

## 10. Shared storage so user work follows them across nodes (NFS)

By default per-user `/work` is a **node-local** volume — if Swarm places a user
on a different node next time, their previous work isn't there. Turn on
**host/NFS storage mode** so every node sees the same data.

Automated path — add `--nfs` on the master and `--nfs-server <ip>` on workers:

```bash
# master:
./setup/master_init.sh --advertise-addr 192.168.1.10 --nfs

# each worker (the master prints this with the token):
sudo ./setup/worker_join.sh --master-ip 192.168.1.10 --join-token ... \
     --node-secret ... --gateway https://192.168.1.10 --nfs-server 192.168.1.10
```

This runs `scripts/setup_nfs.sh` (server on the master, client mount on workers),
exports `/srv/satyameba` to the VLAN, mounts it at the same path everywhere, and
sets `SAT_USER_STORAGE_MODE=host`. The Hub pre-creates each user's dir on the
share (owned by the notebook UID), and both `/home/jovyan/work` and
`/home/jovyan/shared` are then cluster-wide. Keep NFS on a **trusted VLAN** only
(it uses `no_root_squash`).

## 11. High availability (reducing the master SPOF)

A single manager keeps the DB/edge as a single point of failure. To harden:

1. **Three managers (quorum):**
   ```bash
   ./scripts/promote_managers.sh worker2 worker3   # run on the master
   ```
   Swarm tolerates one manager loss with three managers (use an odd count).
2. **Connection pooling (PgBouncer).** Even with one DB, put PgBouncer in front
   so many gateway replicas + the Hub don't exhaust its connection slots:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.pgbouncer.yml up -d
   # swarm: add -c docker-compose.pgbouncer.yml to the stack deploy
   ```
   It repoints the gateway at `pgbouncer:6432` in **session** mode (safe for
   SQLAlchemy). Verify with `./scripts/verify_db.sh`.
3. **Replicate Postgres (remove the DB SPOF).** Two ways:
   * **Bring your own** managed / Patroni / CloudNativePG cluster — point
     `SAT_DATABASE_URL` at it and deploy with `docker-compose.external-db.yml`
     (the bundled db then carries no tasks).
   * **Use the example overlay** `docker-compose.ha-db.yml` — two
     `postgresql-repmgr` nodes (auto-failover) behind `pgpool`:
     ```bash
     docker stack deploy -c docker-compose.swarm.yml \
                         -c docker-compose.ha-db.yml satyameba
     ```
     Set `SAT_REPMGR_PASSWORD` / `SAT_PGPOOL_ADMIN_PASSWORD` first; pin the image
     tags you've tested; then `./scripts/verify_db.sh` shows both nodes + the
     primary. **Validate failover on your hardware before relying on it.**
4. **Edge entry point:** run the edge on each manager and use round-robin DNS or a
   keepalived VIP so clients fail over.

## 12. Owner break-glass, anti-tamper & physical hardening

The `owner-setup/` kit gives the **owner** resilient out-of-band control and an
optional tamper response. Full guide + honest cautions:
[`../owner-setup/README.md`](../owner-setup/README.md).

```bash
# master (installs + guides Tailscale, ensures the un-removable Owner, watchdog):
sudo ./owner-setup/owner_setup.sh --role master \
     --owner-username samaraho --owner-email you@example.com \
     --ssh-pubkey ~/.ssh/id_ed25519.pub --grace-mins 30
#   add --arm-autowipe ONLY when ready for irreversible auto crypto-erase.

# each worker:
sudo ./owner-setup/owner_setup.sh --role worker --ssh-pubkey ~/.ssh/id_ed25519.pub

# host/physical hardening (everywhere) + owner-only source:
sudo ./owner-setup/harden_host.sh           # then the firmware/LUKS checklist it prints
./owner-setup/encrypt_codebase.sh init       # git-crypt owner-only source
```
After setup, set a **Tailscale ACL** so only your identity can SSH the nodes.
The tamper watchdog seals (reversible) on owner/Tailscale removal and, when armed,
crypto-erases after the grace window — **disclose this wipe-on-tamper to students**.

## 13. Backup & restore

```bash
./scripts/backup.sh                       # -> backups/satyameba-<timestamp>/
./scripts/restore.sh backups/satyameba-<timestamp>
```

`backup.sh` dumps Postgres and copies `.env` + `secrets/` (sensitive — store the
archive safely). Add a cron/systemd timer for regular dumps. Also snapshot the
NFS export (or per-user volumes) for notebook contents.

## 14. GPU scheduling & the boost flow

**Prerequisite — the GPU stack (now auto-installed):** the setup wizard /
`master_init.sh --gpu` / `worker_join.sh --gpu` now run
`scripts/setup_nvidia_toolkit.sh` (installs the **NVIDIA Container Toolkit** on
apt/dnf/yum/zypper and registers the runtime) followed by
`scripts/setup_gpu_runtime.sh` (advertises the GPU to Swarm **and** sets
`default-runtime=nvidia`). The one thing still on you is the **kernel driver**
(needs a reboot, and Secure-Boot signing): RTX 5070 / Blackwell needs a **555+**
driver — the toolkit script detects a missing driver and tells you the exact
per-distro command.

**Verify it actually works** (turns the design's assumptions into pass/fail):

```bash
sudo ./scripts/verify_gpu.sh
```

It checks the driver, `default-runtime=nvidia`, that `NVIDIA_VISIBLE_DEVICES=all`
exposes the GPU (shared notebooks) while `=void` hides it (CPU notebooks stay
off the card), and that the GPU is advertised to Swarm (exclusive reservation).
Reference stack: driver ≥ 555, nvidia-container-toolkit ≥ 1.14, Docker ≥ 24,
CUDA base image 12.x.

Then:

* **Exclusive vs. shared** is automatic — see *Scaling* in `CHARACTERISTICS.md`.
* **Boost**: a user clicks **Request more GPUs** (SPA workspace, or the in-Lab
  strip's button); an admin approves under **Admin → Boosts** (and can adjust the
  node count). The user's next launch is boosted for one session; inside it,
  `satyameba-ddp train.py …` wraps `torchrun` with the injected rendezvous.
* **Drain a node** before a reboot under **Admin → Nodes → Drain** (running
  notebooks are left alone; no new ones land there).

> Validate GPU sharing on real hardware: single-host sharing is native; the
> multi-node Swarm path (reserve-for-exclusive vs. `NVIDIA_VISIBLE_DEVICES=all`
> for shared) depends on `default-runtime=nvidia` and your driver/toolkit.

## 15. Remote / off-VLAN nodes (Tailscale)

Same-VLAN workers use `worker_join.sh` (no Tailscale). For a node **elsewhere**
(another building, a home machine), use the *separate* Tailscale wizard so the
two paths never get confused:

```bash
sudo ./setup/remote_node_join.sh \
     --master-ts-ip 100.x.y.z --join-token SWMTKN-... --node-secret <secret> \
     [--authkey tskey-...] [--gpu] [--compute-only]
```

It installs Tailscale (outbound-only WireGuard, no router config), joins the
swarm advertising its **tailnet** IP, registers, and starts a heartbeat. Use
`--compute-only` for an untrusted location (keep NFS/persistent data off it).

## 16. Headless nodes: uninstall the desktop + boot services + console TUI

Free the RAM a desktop eats and run the platform as boot services:

```bash
sudo ./setup/install_services.sh --mode compose --tui   # or --mode swarm
sudo ./setup/uninstall_desktop.sh                       # boot-to-console (reversible)
sudo ./setup/uninstall_desktop.sh --purge --yes         # also remove the DE (autodetected)
sudo ./setup/reinstall_desktop.sh                       # undo any time
```

* `install_services.sh` registers `satyameba.service` (whole stack at boot) and,
  with `--tui`, `satyameba-tui.service` which owns **tty1**.
* The **curses dashboard** (`tui/satyameba_tui.py`, also runnable on demand as
  `satyameba-tui` over SSH) shows live per-node health + active users at any
  resolution, reading `/etc/satyameba/node.env`.
* Default uninstall just switches the boot target to console (instant RAM win,
  fully reversible); `--purge` removes the autodetected DE on any distro.

## 17. Database migrations (Alembic — automatic)

The schema is **Alembic-managed**, so upgrades never lose or skip changes:

* The gateway runs `alembic upgrade head` **at startup** — nothing to do on a
  normal deploy. It's idempotent and **multi-replica-safe** (a Postgres advisory
  lock serializes replicas).
* A pre-Alembic database (one built by the old `create_all`) is **adopted**
  automatically: missing tables are created, then it's stamped at head.
* When you change `gateway/app/models.py`, generate a migration and commit it:

  ```bash
  ./scripts/migrate.sh revision --autogenerate -m "add quota column"   # review it!
  ./scripts/migrate.sh                # upgrade to head (or just restart the gateway)
  ./scripts/migrate.sh current        # what revision is the DB on?
  ./scripts/migrate.sh downgrade -1   # roll back one
  ```

  CI runs `alembic check` — if you change a model without a migration, the build
  fails, so the schema and the code can't silently drift apart.

## 18. Per-user at-rest encryption (gocryptfs)

Encrypt each user's notebook data so the disk only ever holds ciphertext:

```bash
sudo ./setup/gocryptfs_setup.sh      # on each node: installs gocryptfs, KEK,
                                      # cipher/plain bases, the mount agent
./scripts/set_env.sh SAT_USER_ENCRYPTION gocryptfs
./scripts/set_env.sh SAT_USER_STORAGE_MODE host
# redeploy (compose: docker compose up -d  |  swarm: docker stack deploy ...)
```

The all-in-one wizard (`setup/install_wizard.sh`) offers this as a step.

* Per-user keys are `HMAC(owner KEK, sid)` — all anchored to the one KEK in the
  owner keystore, so the **crypto-erase** shreds the KEK + every `gocryptfs.conf`
  and renders *all* user data permanently unreadable instantly.
* The host `satyameba-cryptagent` mounts each user's **decrypted view** on demand
  (and at boot); the notebook bind-mounts that view. The underlying disk/NFS only
  holds ciphertext.
* **Threat covered:** a stolen / pulled / decommissioned drive (powered off) is
  unreadable. **Not covered:** while a notebook is running, its view is decrypted,
  so root on *that* node can read live data — protect-at-rest, not in-use.
* Needs FUSE + `user_allow_other` (the setup script enables it). Validate the
  bind-mount-of-FUSE behaviour on your real hardware.
