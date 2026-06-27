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

    spawner.log.info("spawning %s with profile=%s (%s, %s cpu, gpu=%s)",
                     spawner.user.name, profile, p["mem"], p["cpu"], want_gpu)


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

_volumes = {"satyameba-user-{username}": "/home/jovyan/work"}
if SHARED_VOLUME:
    _volumes[SHARED_VOLUME] = {"bind": "/home/jovyan/shared", "mode": SHARED_MODE}

if SPAWNER == "swarm":
    c.JupyterHub.spawner_class = "dockerspawner.SwarmSpawner"
    c.SwarmSpawner.image = NOTEBOOK_IMAGE
    c.SwarmSpawner.network_name = NETWORK_NAME
    c.SwarmSpawner.remove = True
    c.SwarmSpawner.volumes = _volumes
else:
    c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
    c.DockerSpawner.image = NOTEBOOK_IMAGE
    c.DockerSpawner.network_name = NETWORK_NAME
    c.DockerSpawner.remove = True
    c.DockerSpawner.use_internal_ip = True
    c.DockerSpawner.volumes = _volumes
    # Baseline isolation hardening (profile hook layers resources on top).
    c.DockerSpawner.extra_host_config = {
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
    }

# --- Cull idle servers to free resources ------------------------------------
c.JupyterHub.services.append(
    {
        "name": "idle-culler",
        "command": ["python3", "-m", "jupyterhub_idle_culler",
                    "--timeout=3600", "--cull-every=300"],
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
