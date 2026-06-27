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

Two layers:
1. **Service load balancing** — the edge and Swarm's routing mesh distribute
   gateway/API traffic across gateway replicas.
2. **Workload placement** — when a user launches a notebook, SwarmSpawner
   submits a service and the Swarm scheduler places it on the node with spare
   capacity (and a free GPU, when the user's workload requests one via the
   `node.labels.satyameba.gpu==true` constraint).

## Request lifecycle (launch a notebook)

1. SPA → `POST /api/notebooks/launch` (bearer JWT + HMAC signature).
2. Gateway verifies token + signature, ensures the Hub user exists, asks the
   Hub to start the server, returns the Hub URL.
3. Browser opens the Hub URL; the Hub authenticator confirms the user is
   **approved** via the gateway before the sandbox starts.
4. Swarm schedules the sandbox container on an available worker.
