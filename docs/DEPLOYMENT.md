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

## 0.5 One-button TUI wizard (no desktop needed)

For a headless box or over SSH, run the single wizard that does everything step
by step (deps → Docker → secrets → scan → bring-up → GPU/multi-node/services):

```bash
sudo ./setup/wizard.sh
```

It uses `whiptail`/`dialog` (falling back to plain prompts), works at **any
resolution**, and on any distro (apt/dnf/yum/pacman/zypper/apk via
`scripts/lib_pkg.sh`). Pick **Single host** for the one-shot bring-up.

## 1. Single machine (quickest)

```bash
sudo python3 setup/satyameba_setup.py     # role: Master, tick "Single-host" (desktop GUI)
sudo ./setup/wizard.sh                     # or the TUI wizard → "Single host"
./setup/master_init.sh --single --gpu      # or fully headless
```
Open `https://localhost/`. The admin credentials are in the generated `.env`.

## 2. The 4-desktop lab (Swarm)

### On the master

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
2. **Replicate Postgres** and point `SAT_DATABASE_URL` at it, then deploy with
   the external-db overlay so the bundled db carries no tasks:
   ```bash
   docker stack deploy -c docker-compose.swarm.yml \
                       -c docker-compose.external-db.yml satyameba
   ```
   Bring your own HA Postgres (Patroni / CloudNativePG / managed) — intentionally
   not auto-provisioned.
3. **Edge entry point:** run the edge on each manager and use round-robin DNS or a
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

GPU notebooks need `SAT_GPU_ENABLED=true` and `scripts/setup_gpu_runtime.sh` on
each GPU node (it advertises the GPU to Swarm **and** sets `default-runtime=nvidia`
so concurrent-share notebooks can see the card). Then:

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
