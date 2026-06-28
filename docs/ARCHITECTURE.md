# SATYAMEBA — Architecture

```
                          ┌──────────────────────── MASTER (Swarm manager) ────────────────────────┐
   Internet / LAN         │                                                                          │
        │                 │   ┌──────────┐   only 80/443 published                                   │
        ▼                 │   │   edge    │  (nginx: TLS, SPA, reverse proxy, rate-limit)             │
  https://master ─────────┼──▶│  (nginx)  │                                                          │
                          │   └────┬─────┬┴───────────┬───────────────┐                              │
                          │        │     │            │               │                              │
                          │        ▼     ▼            ▼               ▼                              │
                          │   ┌────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                      │
                          │   │gateway │ │jupyterhub│ │ grafana  │ │prometheus│                      │
                          │   │(FastAPI│ │  (+spawn)│ │          │ │          │                      │
                          │   │  +ORM) │ └────┬─────┘ └──────────┘ └────┬─────┘                      │
                          │   └───┬────┘      │ swarm scheduler          │ scrapes                    │
                          │       │           │ places notebooks         │                            │
                          │   ┌───▼────┐      │                          │                            │
                          │   │postgres│      │                          │                            │
                          │   └────────┘      │                          │                            │
                          └───────────────────┼──────────────────────────┼────────────────────────────┘
                                              │ overlay network          │
              ┌───────────────────────────────┼──────────────────────────┼───────────────┐
              ▼                                ▼                          ▼               ▼
        ┌───────────┐                   ┌───────────┐              ┌───────────┐    ┌───────────┐
        │ WORKER 1  │                   │ WORKER 2  │              │ WORKER 3  │    │  …        │
        │ notebook  │  isolated         │ notebook  │              │ node-exp  │    │           │
        │ container │  per-user         │ container │              │ cadvisor  │    │           │
        │ node-exp  │                   │ node-exp  │              │ dcgm      │    │           │
        │ cadvisor  │                   │ cadvisor  │              │           │    │           │
        │ dcgm(gpu) │                   │ dcgm(gpu) │              │           │    │           │
        └───────────┘                   └───────────┘              └───────────┘    └───────────┘
```

## Components

| Service | Role |
|---------|------|
| **edge** (nginx) | The only entry point. Terminates TLS, serves the SPA, reverse-proxies `/api`, `/hub`, `/user`, `/grafana`. Publishes **only** 80/443. |
| **gateway** (FastAPI + SQLAlchemy) | Identity & control plane: registration, admin approval, login, JWT issuance, request-signature verification, audit log, node registry, notebook brokering. |
| **postgres** | System of record: users, sessions, nodes, tamper-evident audit log. Accessed exclusively through the ORM. |
| **jupyterhub** | Notebook execution engine. Authenticates against the gateway, spawns one **isolated** single-user container per user. |
| **notebook** image | The sandbox a user actually runs in (JupyterLab + data/ML stack), hardened: `cap_drop=ALL`, `no-new-privileges`, CPU/mem caps, private volume, optional GPU. |
| **prometheus** | Scrapes node-exporter (host CPU/mem/net/disk), cAdvisor (per-container), DCGM (GPU) from every node. |
| **grafana** | Renders the cluster dashboard embedded in the admin UI. |

## Why these choices

* **JupyterHub** is the proven multi-user notebook engine — it already solves
  per-user spawning, lifecycle, and isolation. We delegate identity to the
  gateway so approval/suspension is the single source of truth.
* **Docker Swarm** gives master⇄worker join over a single token, an overlay
  network, GPU-aware placement, and service load-balancing with zero extra
  moving parts — the master literally "accepts incoming worker connections" on
  `:2377`, exactly the topology requested.
* **Single edge proxy** keeps the externally reachable surface down to 80/443.

## Load balancing

Three layers:
1. **Service load balancing** — the edge and Swarm's routing mesh distribute
   gateway/API traffic across gateway replicas.
2. **GPU-aware placement (the gateway decides)** — `gateway/app/scheduler.py`
   chooses the node and sharing mode *before* asking the Hub to spawn, so it can
   give each user a whole node while the cluster is quiet (A ≤ N) and switch to
   concurrent GPU sharing when it's busy (A > N), or spread an admin-approved
   **boost** across every free GPU node. Placement is recorded authoritatively in
   `notebook_runs`; the Hub honours the node pin / reservation the gateway passes.
   New supporting models: `gpu_boost_requests`, `notebook_runs`, `notifications`.
3. **Swarm placement** — SwarmSpawner submits the service with the gateway's
   constraints (`node.hostname==…`, `node.labels.satyameba.gpu==true`, and a GPU
   reservation for exclusive jobs vs. `NVIDIA_VISIBLE_DEVICES=all` for shared).

The console **curses TUI** (`tui/`) reads `GET /api/nodes/dashboard` for an
on-monitor view of node health + active users when the desktop is removed.

## Request lifecycle (launch a notebook)

1. SPA → `POST /api/notebooks/launch` (bearer JWT + HMAC signature).
2. Gateway verifies token + signature, ensures the Hub user exists, asks the
   Hub to start the server, returns the Hub URL.
3. Browser opens the Hub URL; the Hub authenticator confirms the user is
   **approved** via the gateway before the sandbox starts.
4. Swarm schedules the sandbox container on an available worker.
