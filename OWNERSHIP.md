# SATYAMEBA — Ownership & Provenance

**Project:** SATYAMEBA — self-hosted, Colab-style Jupyter notebook cloud
**Owner / Author:** **Samaraho Mukherjee**
**Copyright:** © 2026 Samaraho Mukherjee. All rights reserved.

## Cryptographic attribution

The ownership of this codebase is established by a signed integrity manifest:

| Artifact | Purpose |
|----------|---------|
| `SHA256SUMS` | SHA-256 digest of every tracked source file in the repository. |
| `SHA256SUMS.asc` | Detached OpenPGP signature over `SHA256SUMS`, produced with the Owner's private key. |
| `OWNERSHIP.md` (this file) | Human-readable declaration of authorship. |

### Produce the signature (run by the Owner, once)

```bash
# Uses the Owner's GnuPG key. KEYID is e.g. an email or fingerprint.
./scripts/sign_release.sh --key "Samaraho Mukherjee <KEYID>"
```

This regenerates `SHA256SUMS`, signs it into `SHA256SUMS.asc`, and creates an
annotated, GPG-signed git tag.

### Verify ownership & integrity (run by anyone)

```bash
./scripts/verify_release.sh            # checks digests
gpg --verify SHA256SUMS.asc SHA256SUMS # checks the Owner's signature
```

A successful `gpg --verify` against Samaraho Mukherjee's public key proves that
this exact set of files was released and attributed by the Owner, and that no
file has been altered since.

> Note: the detached signature requires the Owner's private key, which is never
> committed to the repository. The repository ships the manifest and the
> tooling; the Owner runs `sign_release.sh` to bind the signature.
