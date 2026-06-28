# SATYAMEBA — Security Model

This document maps SATYAMEBA's controls to the **OWASP Top 10 (2021)** and is
honest about what each control does and does **not** achieve.

## OWASP Top 10 coverage

| # | Risk | Control in SATYAMEBA |
|---|------|----------------------|
| A01 | Broken Access Control | Every privileged route requires a valid, unexpired, non-revoked session (`deps.require_admin`, `get_current_user`). Admin actions are role-checked server-side; the SPA is never trusted. Suspending a user revokes all sessions immediately. |
| A02 | Cryptographic Failures | Passwords hashed with **bcrypt** (cost 12). Access tokens are **RS256** JWTs (private key never leaves the gateway). TLS 1.2/1.3 only at the edge. Per-session HMAC signing keys. Secrets are generated, file-mounted, and git-ignored. |
| A03 | Injection | **All** DB access goes through the SQLAlchemy ORM with bound parameters — no string-built SQL. Strict Pydantic validation on every input. CSP restricts script sources to mitigate XSS. |
| A04 | Insecure Design | Approval-gated onboarding, least-privilege containers, short-lived tokens with rotation, rate limits, tamper-evident audit chain — security designed in, not bolted on. |
| A05 | Security Misconfiguration | Hardened security headers (HSTS, CSP, X-Frame-Options DENY, nosniff, Referrer-Policy). Containers run as non-root with dropped capabilities. Only 80/443 exposed. `server_tokens off`. API docs disabled in production. |
| A06 | Vulnerable Components | Pinned image tags and pinned Python deps for reproducible, auditable builds. Update by bumping pins and rebuilding. |
| A07 | Identification & Auth Failures | Strong password policy, login throttling + temporary lockout after repeated failures, generic error messages (no user enumeration), refresh-token rotation, session revocation. |
| A08 | Software & Data Integrity | Release signed via `SHA256SUMS` + detached GPG signature (see `OWNERSHIP.md`). Audit log is hash-chained. |
| A09 | Logging & Monitoring Failures | Append-only, **hash-chained** audit log of every privileged action; `/api/admin/audit/verify` detects tampering. Prometheus + Grafana for operational visibility. |
| A10 | SSRF | The gateway only talks to a fixed, known set of internal hosts (Hub, DB). No user-controlled URLs are fetched server-side. |

## Request signing (anti-replay / anti-tamper)

Each login issues a per-session HMAC key. The SPA signs every state-changing
request:

```
signature = HMAC-SHA256(session_key,
              METHOD \n PATH \n TIMESTAMP \n NONCE \n SHA256(body))
```

The gateway rejects requests whose timestamp is outside a ±120 s window or whose
nonce was already seen (hard replay block), and recomputes the HMAC from the
server-side session key.

**What this defeats:** captured-and-replayed requests, body/parameter tampering,
and tokens lifted without the signing key.

**What it does *not* do (and why claiming so would be dishonest):** it cannot
hide traffic from a user who proxies *their own* live browser session through
Burp Suite. Anything the browser can compute, the browser's owner can observe.
The defense against a *malicious authenticated user* is authorization +
sandboxing + rate-limits + the audit trail, not request signing.

## Client-side JS "encryption"

The edge can ship **minified + obfuscated** JS (`make obfuscate`). This raises
the effort for casual reverse-engineering only. **It is never a security
boundary** — all authorization and validation are enforced server-side. Treat
the client as fully untrusted.

## Bot filtering

Best-effort UA/header heuristics drop obvious scanners (sqlmap, nikto, …) and
malformed API clients. Determined adversaries can forge headers; the durable
controls are approval gating, rate limiting, and request signing.

## Notebook sandbox isolation

Each user's notebook runs in its own container with:
* `cap_drop: ALL` and `no-new-privileges`
* CPU and memory limits (`SAT_CPU_LIMIT`, `SAT_MEM_LIMIT`)
* a private named volume — **no host bind mounts**
* placement on the internal overlay network only
* idle-culling to reclaim resources

> For stronger multi-tenant isolation against container-escape, run notebooks
> under gVisor (`runsc`) or Kata Containers — documented in DEPLOYMENT.md as an
> optional hardening step.

## Owner control plane (break-glass)

A separate, out-of-band layer that survives a hostile co-admin (`owner-setup/`):
- **Un-removable Owner role** — cannot be demoted/suspended/deleted by anyone, and
  nobody can be promoted to owner.
- **Tailscale tunnel** — outbound-only WireGuard (no router config), SSO + ACL,
  super-user SSH to any node from anywhere; independent of the app's admin model.
- **Tamper watchdog** — if the Owner account or Tailscale is removed, the platform
  **seals** (halt + lock + alert) and, when **armed**, **crypto-erases** all data
  after a grace window (two-stage so a blip can't nuke the lab). Owner-triggered
  **panic** wipe too. *Crypto-erase destroys keys, not via slow overwrite; it is
  irreversible — disclose wipe-on-tamper to students for consent.*
- **Physical hardening** (`harden_host.sh`) + LUKS/BIOS/TPM/Secure-Boot checklist.

## Additional hardening

- **TOTP two-factor auth.** Any user can enrol a TOTP authenticator
  (`/api/auth/2fa/*`); once enabled, login requires the 6-digit code. The login
  flow returns `otp_required` so the SPA can prompt. Set `SAT_REQUIRE_ADMIN_2FA`
  to require it for admins.
- **Forced password rotation.** The seeded bootstrap admin is flagged
  `must_change_password`; the SPA shows a banner until it's changed, and changing
  a password revokes all *other* sessions.
- **Stronger sandbox runtime (gVisor).** `scripts/setup_gvisor.sh` installs
  `runsc` and registers it with Docker; set `SAT_SANDBOX_RUNTIME=runsc` to run
  every notebook under gVisor's syscall-intercepting sandbox — real defense
  against container escape by a malicious approved user.
- **Content-Security-Policy on the SPA.** The edge serves the app with a strict
  CSP (`default-src 'self'`, `object-src 'none'`, `frame-ancestors 'self'`) plus
  HSTS/nosniff/Referrer-Policy, shrinking the XSS blast radius.
- **SSO token not logged.** The one-time-token handoff URL is served with
  `access_log off` so the token never lands in the edge access log.

- **Internal endpoints are edge-blocked.** `/api/internal/*` returns 404 at the
  edge — those routes are only reachable container-to-container, not from outside.
- **Trustworthy client IP.** The gateway takes the **rightmost** `X-Forwarded-For`
  hop (the one our edge appended), so a spoofed header can't bypass rate limits or
  poison the audit log.
- **Fail-closed in production.** The gateway refuses to start if RS256 keys are
  missing or default secrets are still in place — no silent fallback to a weak,
  forgeable HS256 token.
- **TOTP secrets encrypted at rest** with Fernet, keyed from a secret that lives
  in `.env`/docker-secret, not the database — a DB-only dump can't mint codes.
- **2FA brute-force is locked**, not just rate-limited, after repeated bad codes.
- **Admin recovery without back-doors** — admins can reset a user's 2FA or
  password (one-time temp + forced change) or delete the account; all audited.
- **Scoped in-notebook traffic token.** The in-Lab traffic widget reads the
  user's placement through a **narrow, read-only JWT** (`type=traffic`) injected
  into their container at spawn. It can do nothing but read *that* user's own
  cluster view — no session, no mutations — so it's harmless even though the
  user controls their container, and the notebook's server extension proxies it
  server-side so the token never reaches browser JS. The internal shared secret
  is **never** placed in a user notebook.
- **GPU boost is admin-gated and one-shot.** Multi-GPU/cross-node power requires
  an explicit admin approval (audited) and is consumed by a single launch, so a
  user can't self-escalate cluster resources. Node drain is admin-only + audited.

### Token storage (an accepted tradeoff)

Access/refresh tokens and the request-signing key live in **`sessionStorage`**,
which is readable by JavaScript and therefore by any XSS. We mitigate this with a
strict CSP, output escaping, and clearing on tab close. The alternative —
httpOnly cookies — would hide tokens from JS but introduce CSRF surface and
complicate the cross-service (Hub/Grafana) flows. Given the strict CSP and the
VLAN-internal threat model, sessionStorage is the deliberate choice; revisit it
if the platform is ever exposed to the public internet.

> Still deferred (needs your identity provider): OIDC/LDAP institutional login.
> The integration point is the gateway authenticator + a new
> `/api/internal/authenticate`-style adapter; documented as a future option.

## Operational hardening checklist

- [ ] Replace the self-signed cert with a CA/Let's Encrypt cert.
- [ ] Change the bootstrap admin password on first login (the SPA prompts).
- [ ] Enrol TOTP 2FA for admin accounts (set `SAT_REQUIRE_ADMIN_2FA=true`).
- [ ] For less-trusted users, run notebooks under gVisor (`SAT_SANDBOX_RUNTIME=runsc`).
- [ ] Restrict `:2377`, `:7946`, `:4789` (swarm) to the VLAN with a host firewall.
- [ ] Put the database on an encrypted volume.
- [ ] Rotate `SAT_INTERNAL_SHARED_SECRET` and the JWT keypair periodically.
- [ ] Sign the release with the Owner's GPG key (`make sign KEY=...`).
