# SATYAMEBA — Owner Setup (break-glass control, anti-tamper, physical hardening)

**Owner: Samaraho Mukherjee.** This kit gives *you* resilient, out-of-band
super-user control of the cluster from anywhere, makes your Owner account
un-removable, and (optionally) destroys the data if your control is stripped.

> ⚠️ **Read this whole file first.** Part of this kit performs an **irreversible
> data wipe**. Misconfiguration or arming it carelessly can destroy real student
> research. The grace window and "armed" flag exist to protect you from that.

## What's here
| File | Purpose |
|------|---------|
| `owner_setup.sh` | **Run once per node.** Installs + guides you through Tailscale (no router config), adds your break-glass SSH key, ensures the un-removable **Owner** account (master), installs the tamper watchdog. |
| `watchdog.sh` | Master timer: if Tailscale **or** your Owner account disappears → **seal** (halt + lock + alert); if armed and tamper persists past the grace window → **crypto-erase**. |
| `panic.sh` | You trigger it over the tunnel: instant, irreversible crypto-erase + takedown. |
| `lib_crypto.sh` | Keystore + seal/wipe primitives (crypto-erase = destroy keys, not overwrite). |
| `harden_host.sh` | Software host hardening + the firmware/physical checklist. |
| `encrypt_codebase.sh` | Owner-only encrypted source (git-crypt) + images-only distribution to workers. |

## Recommended order
```bash
# On the MASTER (as root):
sudo ./owner-setup/owner_setup.sh --role master \
     --owner-username samaraho --owner-email you@example.com \
     --ssh-pubkey ~/.ssh/id_ed25519.pub \
     --grace-mins 30 --alert-cmd 'curl -s "https://your-webhook"'
#   add --arm-autowipe ONLY when you're ready for irreversible auto-wipe.

# On EACH WORKER (as root):
sudo ./owner-setup/owner_setup.sh --role worker --ssh-pubkey ~/.ssh/id_ed25519.pub

# Everywhere — physical/host hardening:
sudo ./owner-setup/harden_host.sh        # then do the firmware checklist it prints

# Owner-only source confidentiality (on your trusted machine):
./owner-setup/encrypt_codebase.sh init   # git-crypt with your GPG key
./owner-setup/encrypt_codebase.sh images # build + ship images, no source on workers
```
After `owner_setup.sh`, **set a Tailscale ACL in the admin console so only your
identity can SSH the nodes.** Then you can `ssh root@satyameba-master-…` from
anywhere, on any network, with no port-forwarding.

## How it meets your requirements
- **From anywhere, no router config** — Tailscale (WireGuard) dials *outbound*;
  NAT/CGNAT-proof via DERP relays.
- **Survives being removed as admin** — the tunnel + Owner role are a *separate
  control plane*; a hostile co-admin can't touch either. The Owner account
  cannot be demoted/suspended/deleted by anyone in the app.
- **Tamper → everything goes down** — the watchdog seals immediately and (when
  armed) crypto-erases after the grace window.

## The wipe, honestly
- It's **crypto-erase**: the root key and each encrypted folder's key file are
  shredded, so terabytes become unrecoverable ciphertext **instantly**. Faster
  and cleaner than overwriting, equally permanent.
- **Two stages** so a blip can't nuke the lab: *seal* (recoverable) fires first;
  *wipe* only escalates if you **armed** it and tamper persists past `--grace-mins`.
  You get alerts and can cancel from your phone over the tunnel in that window.
- **Scope: your 4 nodes only.** It never touches anything you don't own and
  doesn't spread.
- **Tell your students** their data is wiped-on-tamper. It's their research;
  their consent protects you. Put it in your lab policy.

## Recovery (no tamper, you just need back in)
1. SSH in over Tailscale. 2. Restore whatever tripped it (re-add Owner role in the
DB, or `tailscale up`). 3. The watchdog clears the tamper mark on the next tick;
`docker stack deploy`/`compose up` to bring services back. (Only *seal* is
reversible — once *wipe* runs, data is gone by design.)

## Honest limits (don't let anyone tell you otherwise)
- **Code that runs on a node can be read by root on that node.** `encrypt_codebase.sh`
  protects the repo/host/backups and keeps source off workers — it can't hide a
  live process from a root user. Same truth as "encrypted JS."
- **A running notebook needs plaintext**, so the server (and root) can read live
  data while it runs. Per-user encryption protects data at rest / other students
  / backups / dormant snooping — not the running computation.
- **Physical access ultimately wins in software terms.** LUKS + BIOS/GRUB
  passwords + Secure Boot + TPM-bound keys + a locked rack are the real physical
  defense; this kit raises the bar and makes *your* access resilient, but a
  determined attacker with the disk in hand is the unbeatable class.
- **Unverified on hardware here** — these scripts are written carefully and
  lint-clean, but were not run on real Tailscale/root/Docker. Test on one node
  before trusting the fleet.
