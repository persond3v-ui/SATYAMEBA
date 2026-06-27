# SATYAMEBA JupyterHub configuration
#
# Spawner modes (SAT_SPAWNER):
#   * docker — single host: each notebook is an isolated container locally.
#   * swarm  — multi-node: notebooks are Swarm services the scheduler spreads
#              across the cluster (and onto GPU-labelled nodes when requested).
#
# Resource PROFILES make scheduling payload-aware: the user picks a size in the
# SPA, the gateway passes it as a spawn option, and we reserve CPU/RAM/GPU
# accordingly so Swarm distributes work by the requested footprint.
import hashlib
import os

c = get_config()  # noqa: F821

SPAWNER = os.environ.get("SAT_SPAWNER", "docker").lower()
NOTEBOOK_IMAGE = os.environ.get("SAT_NOTEBOOK_IMAGE", "satyameba/notebook:latest")
NETWORK_NAME = os.environ.get("SAT_NETWORK", "satyameba_net")
GPU_ENABLED = os.environ.get("SAT_GPU_ENABLED", "false").lower() == "true"
GPU_RESOURCE = os.environ.get("SAT_GPU_RESOURCE", "gpu")
DEFAULT_MEM = os.environ.get("SAT_MEM_LIMIT", "4G")
DEFAULT_CPU = float(os.environ.get("SAT_CPU_LIMIT", "2"))
SHARED_VOLUME = os.environ.get("SAT_SHARED_VOLUME", "satyameba-shared")
SHARED_MODE = os.environ.get("SAT_SHARED_MODE", "rw")  # rw or ro
STORAGE_LIMIT_GB = os.environ.get("SAT_USER_STORAGE_LIMIT_GB", "")
STORAGE_ENFORCE = os.environ.get("SAT_STORAGE_QUOTA_ENFORCE", "false").lower() == "true"

# Storage mode:
#   volume — node-local Docker named volume (single-host default).
#   host   — bind-mount from a host path that is the SAME on every node (an NFS
#            mount), so a user's work follows them wherever Swarm places them.
USER_STORAGE_MODE = os.environ.get("SAT_USER_STORAGE_MODE", "volume").lower()
USER_HOST_BASE = os.environ.get("SAT_USER_HOST_BASE", "/srv/satyameba/users")
SHARED_HOST_PATH = os.environ.get("SAT_SHARED_HOST_PATH", "/srv/satyameba/shared")
NB_UID = int(os.environ.get("SAT_NB_UID", "1000"))
NB_GID = int(os.environ.get("SAT_NB_GID", "100"))
# Optional stronger sandbox runtime (e.g. "runsc" for gVisor). Empty = default.
SANDBOX_RUNTIME = os.environ.get("SAT_SANDBOX_RUNTIME", "").strip()

# Resource profiles (payload-aware scheduling).
PROFILES = {
    "small":  {"mem": "2G",        "cpu": 1.0,         "gpu": 0},
    "medium": {"mem": DEFAULT_MEM, "cpu": DEFAULT_CPU, "gpu": 0},
    "large":  {"mem": "8G",        "cpu": 4.0,         "gpu": 0},
    "gpu":    {"mem": "8G",        "cpu": 4.0,         "gpu": 1},
}


def _mem_bytes(s: str) -> int:
    s = s.strip().upper()
    mult = {"G": 1024**3, "M": 1024**2, "K": 1024}.get(s[-1:], 1)
    return int(float(s[:-1]) * mult) if s[-1:] in "GMK" else int(s)


def _storage_key(spawner) -> str:
    """Meaningless, stable per-account folder name. Uses the gateway-supplied
    'sid' (hash of the IMMUTABLE account id) so names reveal nothing and a reused
    username can never inherit a deleted account's files (N2/N3)."""
    sid = (spawner.user_options or {}).get("sid")
    if not sid:
        sid = hashlib.sha256(spawner.user.name.encode()).hexdigest()[:16]
    return f"u-{sid}"


def _set_volumes(spawner, key: str) -> None:
    if USER_STORAGE_MODE == "host":
        vols = {os.path.join(USER_HOST_BASE, key): "/home/jovyan/work"}
        if SHARED_HOST_PATH:
            vols[SHARED_HOST_PATH] = {"bind": "/home/jovyan/shared", "mode": SHARED_MODE}
    else:
        vols = {f"satyameba-{key}": "/home/jovyan/work"}
        if SHARED_VOLUME:
            vols[SHARED_VOLUME] = {"bind": "/home/jovyan/shared", "mode": SHARED_MODE}
    spawner.volumes = vols


def pre_spawn_hook(spawner):
    """Apply the chosen profile's resource reservation to this server."""
    profile = (spawner.user_options or {}).get("profile", "medium")
    p = PROFILES.get(profile, PROFILES["medium"])
    spawner.mem_limit = p["mem"]
    spawner.cpu_limit = float(p["cpu"])
    want_gpu = bool(p["gpu"]) and GPU_ENABLED

    if SPAWNER == "swarm":
        spec = {"mem_limit": _mem_bytes(p["mem"]), "cpu_limit": int(float(p["cpu"]) * 1e9)}
        if want_gpu:
            spec["generic_resources"] = {GPU_RESOURCE: int(p["gpu"])}
            spawner.extra_placement_spec = {"constraints": ["node.labels.satyameba.gpu==true"]}
        else:
            spawner.extra_placement_spec = {}
        spawner.extra_resources_spec = spec
    else:
        hc = dict(spawner.extra_host_config or {})
        if want_gpu:
            hc["device_requests"] = [
                {"Driver": "nvidia", "Count": int(p["gpu"]), "Capabilities": [["gpu"]]}
            ]
        else:
            hc.pop("device_requests", None)
        if STORAGE_ENFORCE and STORAGE_LIMIT_GB:
            # Requires an xfs prjquota-enabled docker storage driver.
            hc["storage_opt"] = {"size": f"{STORAGE_LIMIT_GB}G"}
        spawner.extra_host_config = hc

    # Per-account, hashed storage (meaningless name; immutable id).
    key = _storage_key(spawner)
    _set_volumes(spawner, key)
    if USER_STORAGE_MODE == "host":
        try:
            d = os.path.join(USER_HOST_BASE, key)
            os.makedirs(d, exist_ok=True)
            os.chown(d, NB_UID, NB_GID)
        except Exception as exc:
            spawner.log.warning("could not prepare host workdir for %s: %s",
                                spawner.user.name, exc)

    spawner.log.info("spawning %s (store=%s) profile=%s (%s, %s cpu, gpu=%s)",
                     spawner.user.name, key, profile, p["mem"], p["cpu"], want_gpu)


# --- Authenticator: delegate to the SATYAMEBA gateway -----------------------
c.JupyterHub.authenticator_class = "satyameba_authenticator.SatyamebaAuthenticator"
c.Authenticator.allow_all = True            # allow-list enforced upstream (approval)

# --- Hub networking ---------------------------------------------------------
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = os.environ.get("SAT_HUB_CONNECT_IP", "jupyterhub")
c.JupyterHub.bind_url = "http://0.0.0.0:8000"
c.JupyterHub.cleanup_servers = True
c.JupyterHub.base_url = "/hub"

c.JupyterHub.services = [
    {
        "name": "satyameba-gateway",
        "api_token": os.environ.get("SAT_HUB_API_TOKEN", "CHANGE_ME_hub_api_token"),
        "admin": True,
    }
]
c.JupyterHub.load_roles = [
    {
        "name": "gateway-admin",
        "services": ["satyameba-gateway"],
        "scopes": ["admin:users", "admin:servers", "tokens"],
    }
]

# --- Spawner: common + per-mode --------------------------------------------
c.Spawner.pre_spawn_hook = pre_spawn_hook
c.Spawner.start_timeout = 180
c.Spawner.http_timeout = 120
# Allow same-origin framing (defense-in-depth; the SPA opens a new tab anyway).
c.Spawner.args = [
    "--ServerApp.tornado_settings={'headers':{'Content-Security-Policy':\"frame-ancestors 'self'\"}}",
]

# Volumes are set per-spawn in pre_spawn_hook (hashed per-account storage key).
if SPAWNER == "swarm":
    c.JupyterHub.spawner_class = "dockerspawner.SwarmSpawner"
    c.SwarmSpawner.image = NOTEBOOK_IMAGE
    c.SwarmSpawner.network_name = NETWORK_NAME
    c.SwarmSpawner.remove = True
else:
    c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
    c.DockerSpawner.image = NOTEBOOK_IMAGE
    c.DockerSpawner.network_name = NETWORK_NAME
    c.DockerSpawner.remove = True
    c.DockerSpawner.use_internal_ip = True
    # Baseline isolation hardening (profile hook layers resources on top).
    _base_hc = {
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
    }
    if SANDBOX_RUNTIME:
        _base_hc["runtime"] = SANDBOX_RUNTIME   # e.g. gVisor's runsc
    c.DockerSpawner.extra_host_config = _base_hc

# --- Cull idle servers to free resources ------------------------------------
c.JupyterHub.services.append(
    {
        "name": "idle-culler",
        # Reclaim abandoned servers quickly (logout already tears down explicitly;
        # this only culls *idle* kernels, so active training is never killed).
        "command": ["python3", "-m", "jupyterhub_idle_culler",
                    "--timeout=1200", "--cull-every=120"],
    }
)
c.JupyterHub.load_roles.append(
    {
        "name": "idle-culler",
        "services": ["idle-culler"],
        "scopes": ["list:users", "read:users:activity", "admin:servers"],
    }
)

# --- Persistence ------------------------------------------------------------
c.JupyterHub.db_url = os.environ.get(
    "SAT_HUB_DB_URL", "sqlite:////srv/jupyterhub/jupyterhub.sqlite"
)
