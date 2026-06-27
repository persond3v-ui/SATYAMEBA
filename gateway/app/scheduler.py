"""Dynamic load balancer — decides which node a notebook lands on and whether
it gets a node to itself or shares one concurrently.

The policy (N = online GPU-capable nodes, A = active notebook runs):

* **A <= N**  → every active user gets a **whole node to themselves**: the
  scheduler pins the launch to an empty node and reserves *all* GPU slices, so
  Swarm won't co-locate anyone else. Full GPU, full VRAM.
* **A >  N**  → all nodes already have an occupant, so the newcomer is placed on
  the **least-loaded** node and **shares it concurrently** (reserves a single
  GPU slice; both kernels run on the same physical GPU at once). The users
  already on that node are **notified** that they're now sharing, and the
  newcomer is **queued** for promotion to a dedicated node when one frees.
* **Admin-approved boost** → the job is spread across every GPU node that is
  free right now (Kaggle-style). At 3 a.m. with nobody else active that is the
  whole cluster. The grant is good for one session.

N is discovered at runtime from the Node table, so adding nodes just raises N —
nothing is hard-coded to four.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import Node, NodeStatus, NotebookRun, Notification
from .timeutil import aware, utcnow

settings = get_settings()


@dataclass
class Placement:
    node: str | None = None          # hostname to pin to (None = let Swarm decide)
    mode: str = "exclusive"          # exclusive | shared | boost
    shared: bool = False
    gpus: int = 0                    # number of GPU nodes this job spans
    ddp_nodes: list[str] = field(default_factory=list)   # boost: all participating hosts
    rdzv: str = ""                   # boost: torchrun rendezvous endpoint
    colocated: list[NotebookRun] = field(default_factory=list)  # runs already on `node`
    queued: bool = False             # newcomer is waiting for a dedicated node


def online_nodes(db: Session, gpu_only: bool = False) -> list[Node]:
    """Nodes with a fresh heartbeat that are not draining/offline."""
    cutoff = settings.node_offline_seconds
    out: list[Node] = []
    for n in db.execute(select(Node)).scalars():
        hb = aware(n.last_heartbeat)
        if hb is None or (utcnow() - hb).total_seconds() > cutoff:
            continue
        if n.status == NodeStatus.draining:
            continue
        if gpu_only and not (n.labels or {}).get("gpu"):
            continue
        out.append(n)
    return out


def active_runs(db: Session) -> list[NotebookRun]:
    return list(
        db.execute(select(NotebookRun).where(NotebookRun.status == "active")).scalars()
    )


def _occupancy(nodes: list[Node], runs: list[NotebookRun]) -> dict[str, int]:
    """How many notebooks each node currently hosts, counting boost-reserved
    peer nodes as occupied so a boosted job isn't trampled mid-session."""
    occ = {n.hostname: 0 for n in nodes}
    for r in runs:
        if r.node_hostname in occ:
            occ[r.node_hostname] += 1
        for h in (r.extra or {}).get("ddp_nodes", []):
            if h in occ and h != r.node_hostname:
                occ[h] += 1
    return occ


def plan_placement(db: Session, username: str, profile: str, boost=None) -> Placement:
    """Decide where this launch goes. ``boost`` is a granted GpuBoostRequest or None."""
    wants_gpu = profile == "gpu" or boost is not None
    nodes = online_nodes(db, gpu_only=wants_gpu)

    # No registered cluster (single-host / dev / tests): nothing to balance.
    if not nodes:
        if boost:
            return Placement(mode="boost", gpus=max(1, boost.gpus), shared=False)
        return Placement(mode="exclusive", shared=False)

    runs = [r for r in active_runs(db) if r.username != username]  # ignore our own stale run
    occ = _occupancy(nodes, runs)

    # --- admin-approved boost: grab every currently-free GPU node ---
    if boost:
        free = [h for h, c in occ.items() if c == 0]
        want = max(1, boost.gpus)
        chosen = free[:want] if free else [min(occ, key=occ.get)]
        primary = chosen[0]
        rdzv = f"{primary}:29400"
        return Placement(node=primary, mode="boost", shared=False,
                         gpus=len(chosen), ddp_nodes=chosen, rdzv=rdzv)

    # --- normal scheduling ---
    empty = [h for h, c in occ.items() if c == 0]
    if empty:
        # A <= N: a whole node to yourself.
        return Placement(node=empty[0], mode="exclusive", shared=False, gpus=1 if wants_gpu else 0)

    # A > N: all nodes busy → least-loaded, share concurrently, notify + queue.
    target = min(occ, key=occ.get)
    colocated = [r for r in runs if r.node_hostname == target]
    return Placement(node=target, mode="shared", shared=True,
                     gpus=1 if wants_gpu else 0, colocated=colocated, queued=True)


def notify(db: Session, user_id: str, kind: str, message: str) -> None:
    db.add(Notification(user_id=user_id, kind=kind, message=message[:512]))


def on_run_stopped(db: Session, freed_host: str) -> None:
    """When a run ends and frees a node, tell the longest-waiting shared user
    that a dedicated node is available (promotion is opt-in via restart so we
    never kill a running kernel)."""
    runs = active_runs(db)
    occ_hosts = {r.node_hostname for r in runs}
    occ_hosts |= {h for r in runs for h in (r.extra or {}).get("ddp_nodes", [])}
    if freed_host in occ_hosts:
        return  # someone else already there
    waiting = sorted((r for r in runs if r.shared), key=lambda r: aware(r.started_at) or utcnow())
    if not waiting:
        return
    nxt = waiting[0]
    nxt.shared = False  # mark it no longer queued so we don't spam
    notify(db, nxt.user_id, "success",
           f"A dedicated GPU node ({freed_host}) just freed up. Restart your "
           "notebook to claim it for yourself.")
