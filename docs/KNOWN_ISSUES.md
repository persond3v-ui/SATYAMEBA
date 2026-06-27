# SATYAMEBA — Known Issues & Flaw Log

An honest, self-audited list of the current limitations and bugs in the Phase-1
core, with severity and remediation. Kept in-repo so deployment decisions are
made with eyes open. Severity: 🔴 high · 🟠 medium · 🟡 low.

## Notebook access / UX

- **I-1 🔴 No SSO to JupyterHub (double login).**
  `POST /api/notebooks/launch` returns a `handshake` token
  (`gateway/app/routers/notebooks.py`), but the Hub authenticator
  (`jupyterhub/satyameba_authenticator.py`) only consumes `username`+`password`.
  The `handshake` is effectively dead code. In practice, when the SPA iframes
  `/hub/user/<name>/`, the browser has no Hub session yet, so the user lands on
  the Hub login page and must re-enter their SATYAMEBA credentials once.
  *Fix:* issue a short-lived one-time token from the gateway and add a custom
  Hub login handler that exchanges it (true SSO), or use JupyterHub `auth_state`.

- **I-2 🟠 JupyterLab may refuse to embed in the iframe.**
  Jupyter Server sets frame-ancestors/X-Frame-Options by default; embedding
  `/hub/user/...` inside the SPA iframe can be blocked.
  *Fix:* set single-user `tornado_settings` headers to allow same-origin
  framing, **or** open the notebook in a new tab instead of an iframe.

- **I-3 🟠 Dataset upload capped at 64 MB.**
  `frontend/nginx.conf` sets `client_max_body_size 64m`; larger uploads through
  the edge fail. *Fix:* raise the limit (or set `0` and rely on Jupyter's own
  limits) and/or document the `jupyter` contents API / mounting external storage.

## Monitoring

- **I-4 🟠 The admin dashboard does not query Prometheus directly.**
  The "Monitoring" tab embeds Grafana via an iframe; the stat cards come from DB
  counts (`/api/admin/stats`) and the Nodes tab from heartbeats. There is no
  gateway endpoint that pulls live CPU/GPU numbers for inline display.
  *Fix:* add a gateway route proxying Prometheus instant queries
  (`/api/v1/query`) for inline per-node sparklines.

- **I-5 🔴 `/grafana/` is not authentication-gated and runs anonymous Viewer.**
  `docker-compose*.yml` enables `GF_AUTH_ANONYMOUS_ENABLED=true` and the edge
  proxies `/grafana/` without auth. Anyone who can reach the edge can read
  cluster dashboards. *Fix:* protect `/grafana/` with an nginx `auth_request`
  against the gateway session, or disable anonymous access and require Grafana
  login; only embed via signed Grafana URLs.

## High availability / scaling

- **I-6 🔴 The master is a single point of failure.**
  All control-plane services (db, gateway×2, jupyterhub, edge, prometheus,
  grafana) are pinned to `node.role == manager`. Workers add compute redundancy
  for *notebooks* only. If the master dies, the platform is down — so
  "fail-proof" is overstated today. *Fix:* multi-manager swarm (3 managers),
  Postgres replication/HA, and spread the edge/gateway across managers.

- **I-7 🟠 Rate limiting & replay-nonce cache are per-replica (in-process).**
  With `replicas: 2` for the gateway, the sliding-window limiter
  (`middleware/rate_limit.py`) and the signing nonce cache
  (`middleware/request_signing.py`) are not shared, so a replay sent to the
  *other* replica within the ±120 s window can slip through, and rate limits are
  effectively doubled. *Fix:* back both with Redis.

## Deployment

- **I-8 🔴 `docker compose up` does not build the notebook image.**
  `satyameba/notebook` is not a compose service, so plain `docker compose up`
  (and `make up`) build the gateway/hub/edge but not the sandbox image; the first
  launch then fails to spawn. Only `setup/master_init.sh` builds it.
  *Fix:* add a one-shot builder service or a `make notebook-image` target, and
  fix the quick-start docs to build it before first launch.

- **I-9 🟠 GPU reservation needs Docker daemon config that the join script does not set.**
  `SwarmSpawner.extra_resources_spec["generic_resources"] = {"gpu": 1}` requires
  each GPU node's `/etc/docker/daemon.json` to advertise
  `node-generic-resources`. `setup/worker_join.sh` labels the node but does not
  write that config. *Fix:* have the join script append the
  `NodeGenericResources` stanza and restart docker on GPU nodes.

- **I-10 🟡 Self-signed TLS by default.** Browsers warn; `worker_join.sh` uses
  `curl -k`. Fine for a lab; document issuing a real/Let's Encrypt cert.

## Scheduling semantics

- **I-11 🟠 "Distribute by payload" is approximated, not real.**
  Swarm spreads notebooks by task count honoring *fixed* per-notebook CPU/mem
  reservations; it does not inspect the actual workload. There is no autoscaling
  and no GPU time-sharing (one notebook reserves a whole GPU). Honest limitation.

- **I-12 🟡 Single-host (compose) mode does not distribute at all.**
  In `--single` mode the DockerSpawner runs every notebook on the one host. Load
  balancing across the 4 desktops only happens in Swarm mode.

## Data

- **I-13 🟠 No shared/team dataset storage.** Each user gets an isolated volume
  (`satyameba-user-<username>`). Shared or very large datasets need an external
  NFS/object-store mount wired into the spawner. Not yet provided.

## Verification gaps

- **I-14 🟠 SwarmSpawner resource-spec keys unverified against the live API.**
  `extra_resources_spec` in `jupyterhub_config.py` is plausible but not yet run
  on a real swarm; key names may need adjusting to dockerspawner's schema.

- **I-15 🟡 No automated test suite / CI in the repo.** The register→approve→
  login→suspend flow, request signing, and audit chain were validated locally,
  but those tests are not committed and don't run on push. *Fix:* add `tests/`
  + a CI workflow.

- **I-16 🟡 Bootstrap admin password sits in `.env` in plaintext** (file mode
  600). Acceptable for a lab; rotate after first login.

---
*Maintained by self-audit. Each item lists a concrete fix so they can be picked
up in priority order.*
