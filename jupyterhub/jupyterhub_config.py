# SATYAMEBA JupyterHub configuration
#
# Two spawner modes, selected by SAT_SPAWNER:
#   * docker  — single-host: each notebook is an isolated container on the
#               local Docker engine (great for the dev/compose deployment).
#   * swarm   — multi-node: notebooks are scheduled as Swarm services across
#               the cluster, so the swarm scheduler load-balances them onto
#               whichever node has capacity / a free GPU.
#
# Isolation hardening applied to every single-user server:
#   - dropped Linux capabilities, no-new-privileges
#   - per-user CPU & memory limits
#   - no bind mounts from the host; only a private named volume per user
#   - placed on an internal overlay/bridge network
import os

c = get_config()  # noqa: F821

SPAWNER = os.environ.get("SAT_SPAWNER", "docker").lower()
NOTEBOOK_IMAGE = os.environ.get("SAT_NOTEBOOK_IMAGE", "satyameba/notebook:latest")
NETWORK_NAME = os.environ.get("SAT_NETWORK", "satyameba_net")
GPU_ENABLED = os.environ.get("SAT_GPU_ENABLED", "false").lower() == "true"
MEM_LIMIT = os.environ.get("SAT_MEM_LIMIT", "4G")
CPU_LIMIT = float(os.environ.get("SAT_CPU_LIMIT", "2"))

# --- Authenticator: delegate to the SATYAMEBA gateway -----------------------
c.JupyterHub.authenticator_class = "satyameba_authenticator.SatyamebaAuthenticator"
c.Authenticator.admin_users = set()  # admin flag comes from the gateway response
c.Authenticator.allow_all = True     # allow-list is enforced upstream (approval)

# --- Hub networking ---------------------------------------------------------
c.JupyterHub.hub_ip = "0.0.0.0"
c.JupyterHub.hub_connect_ip = os.environ.get("SAT_HUB_CONNECT_IP", "jupyterhub")
c.JupyterHub.bind_url = "http://0.0.0.0:8000"
c.JupyterHub.cleanup_servers = True
c.JupyterHub.base_url = "/hub"

# Admin/service token used by the gateway to drive the Hub REST API.
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

# --- Common spawner hardening ----------------------------------------------
common_host_config = {
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "mem_limit": MEM_LIMIT,
}

if SPAWNER == "swarm":
    c.JupyterHub.spawner_class = "dockerspawner.SwarmSpawner"
    c.SwarmSpawner.image = NOTEBOOK_IMAGE
    c.SwarmSpawner.network_name = NETWORK_NAME
    c.SwarmSpawner.remove = True
    c.SwarmSpawner.extra_resources_spec = {
        "mem_limit": int(4 * 1024**3),
        "cpu_limit": int(CPU_LIMIT * 1e9),
    }
    c.SwarmSpawner.extra_placement_spec = {}
    if GPU_ENABLED:
        # Place GPU notebooks only on nodes labelled satyameba.gpu==true and
        # reserve a GPU generic resource (declared in the worker daemon.json).
        c.SwarmSpawner.extra_placement_spec = {
            "constraints": ["node.labels.satyameba.gpu==true"]
        }
        c.SwarmSpawner.extra_resources_spec["generic_resources"] = {"gpu": 1}
else:
    c.JupyterHub.spawner_class = "dockerspawner.DockerSpawner"
    c.DockerSpawner.image = NOTEBOOK_IMAGE
    c.DockerSpawner.network_name = NETWORK_NAME
    c.DockerSpawner.remove = True
    c.DockerSpawner.use_internal_ip = True
    c.DockerSpawner.extra_host_config = dict(common_host_config)
    c.DockerSpawner.mem_limit = MEM_LIMIT
    c.DockerSpawner.cpu_limit = CPU_LIMIT
    # Private per-user volume; no host bind mounts.
    c.DockerSpawner.volumes = {"satyameba-user-{username}": "/home/jovyan/work"}
    if GPU_ENABLED:
        c.DockerSpawner.extra_host_config["device_requests"] = [
            {"Driver": "nvidia", "Count": -1, "Capabilities": [["gpu"]]}
        ]

# --- Culling idle servers to free resources ---------------------------------
c.JupyterHub.services.append(
    {
        "name": "idle-culler",
        "command": [
            "python3", "-m", "jupyterhub_idle_culler",
            "--timeout=3600", "--cull-every=300",
        ],
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
c.Spawner.start_timeout = 120
c.Spawner.http_timeout = 90
