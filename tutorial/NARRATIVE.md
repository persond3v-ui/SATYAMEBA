# SATYAMEBA — Two Stories

The functionality of the platform, told as stories. These scripts are what the
Manim tutorials animate.

---

## Story 1 — The Admin: "Colab, on our own metal"

Dr. Anand runs a four-desktop research lab: each box a Debian machine with an
i7 and an RTX 5070. For months it has been chaos. Students SSH into "the GPU
box," step on each other's conda environments, leave zombie training jobs
pinning the card overnight, and quietly fill the disks. Twice, someone's
`rm -rf` took a labmate's dataset with it. He wants something like Google Colab —
but running on the lab's own hardware, where the data never leaves the building.

He clones **SATYAMEBA** onto the machine he picks as the *master* and runs the
setup wizard:

```
sudo python3 setup/satyameba_setup.py
```

A small window opens with progress bars. He clicks **Check dependencies** — it
inspects Docker, Docker Compose, the NVIDIA driver and Container Toolkit, and
flags what's missing. **Install / fix missing** pulls the rest from the official
repos. **Verify GPU passthrough** spins up a throwaway container and prints
`nvidia-smi` from *inside* it — a green check. Then he clicks **Scan storage &
resources**, and the wizard reads the disk, RAM and cores and writes sensible
per-user limits into `.env`. He didn't have to guess any numbers.

He bootstraps the master:

```
./setup/master_init.sh --advertise-addr 192.168.1.10 --gpu --nfs --users 16
```

In one go it generates the secrets (an RSA keypair for tokens, a TLS cert),
initialises a Docker Swarm so this box becomes the manager, sets up an **NFS
share so a student's work follows them no matter which node they land on**,
configures the GPU runtime for the swarm, builds the images, deploys the whole
stack — and prints a single copy-paste command for the workers.

He walks to the other three desktops and on each runs that printed
`worker_join.sh …`. Each one joins the swarm on port 2377, builds the notebook
sandbox image, mounts the shared storage, and **registers itself**. Back at his
laptop he opens `https://192.168.1.10/`, and there they are under **Admin →
Nodes**: four machines, online, heart-beating, GPUs labelled.

He logs in as the seeded admin — and the dashboard immediately nags him with a
banner: *change your initial password*. He does, then opens his phone, taps
**Set up 2FA**, scans the QR, and from now on his admin login needs a 6-digit
code. (He notices, with mild surprise, that this needs **no third-party
service** — the phone and server just agree on a secret once and compute the
same code from the clock.)

Students start signing up. They land in **Approvals** as *pending* — nobody gets
in without him. He approves the real ones with a click and rejects an obvious
spammer. Later, one student's runaway job pegs a GPU. He opens **Monitoring**:
live CPU / GPU / disk / network for every node, pulled straight from Prometheus,
with full Grafana underneath. He sees exactly which box. **Sessions** shows the
running notebook; one click **kicks the user off** — their sessions are revoked
instantly and their container is killed. Every one of these actions is written
to a **tamper-evident audit log** he can verify hasn't been altered.

What he *didn't* have to do: juggle Linux accounts on four machines, hand-write
Docker commands, track who's on which box, or worry about lost work when a
machine reboots. The only thing exposed to the network is HTTPS on 443.
The lab finally feels like a product.

---

## Story 2 — The User: "Just open your browser and build"

Meera is a grad student who trains vision models. Her old workflow was misery:
SSH into the shared GPU box and pray it's free, rebuild her environment for the
hundredth time, and tiptoe around everyone else's files (she once deleted a
labmate's data by accident). Colab kept disconnecting and would never give her
the lab's shiny RTX 5070.

She opens `https://satyameba.local`, clicks **Register**, and submits her
details. The page says her account is awaiting admin approval — so she waits.
A few minutes later (Dr. Anand approved her), she logs in to a clean web
workspace with her name on it.

She picks a **resource profile** — *GPU · 8 GB · 4 CPU · 1 GPU* — and clicks
**🚀 Launch**. A new browser tab opens **straight into JupyterLab** — no second
login, no waiting room. Behind the scenes the cluster placed her notebook on a
node that had a free GPU; she never had to choose a machine.

It's real JupyterLab. She drags in her **3 GB dataset** — there's **no upload
limit** — and it lands in her private `/work` folder. A shared reference dataset
is already mounted at `/shared`. She writes a few cells, calls `.cuda()`, and her
model trains on the 5070. Crucially, she's in her **own isolated container**:
she couldn't touch anyone else's files if she tried, and nobody can touch hers.

She gets pulled into a meeting. An hour later the **idle culler** quietly
reclaims her container to free the GPU for others — but **her files are safe in
her volume**. When she comes back and launches again, the scheduler happens to
put her on a *different* node — and because of the shared NFS storage, **her work
is right there waiting**, exactly as she left it.

Before she logs off she enables **2FA** from her workspace, scanning the QR with
the same authenticator app, and updates her password. Done.

The problems that used to define her week — SSH roulette, environment setup,
clobbering others, losing the GPU, losing work across machines, Colab timeouts —
are simply gone. She just opens her browser and builds, on the lab's own
hardware, with her data never leaving the building.
