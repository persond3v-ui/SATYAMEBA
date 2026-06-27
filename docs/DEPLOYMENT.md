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

## 1. Single machine (quickest)

```bash
sudo python3 setup/satyameba_setup.py     # role: Master, tick "Single-host"
# or, headless:
./setup/master_init.sh --single --gpu
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

Replace `secrets/certs/satyameba.{crt,key}` with a real certificate (e.g. issue
with certbot using the `/.well-known/acme-challenge/` location already wired in
the edge config), then `docker compose restart edge`.
