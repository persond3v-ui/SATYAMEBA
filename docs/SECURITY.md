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

## Operational hardening checklist

- [ ] Replace the self-signed cert with a CA/Let's Encrypt cert.
- [ ] Change the bootstrap admin password on first login.
- [ ] Restrict `:2377`, `:7946`, `:4789` (swarm) to the VLAN with a host firewall.
- [ ] Put the database on an encrypted volume.
- [ ] Rotate `SAT_INTERNAL_SHARED_SECRET` and the JWT keypair periodically.
- [ ] Sign the release with the Owner's GPG key (`make sign KEY=...`).
