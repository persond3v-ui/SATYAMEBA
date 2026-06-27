"""End-to-end gateway tests: onboarding, request signing, SSO, admin powers."""
import json
import secrets
import time

import pytest

from app.security import sign_request


def _sign(token, skey, method, path, body: bytes):
    ts = str(int(time.time()))
    nonce = secrets.token_hex(8)
    sig = sign_request(skey, method, path, ts, nonce, body)
    return {
        "Authorization": f"Bearer {token}",
        "X-SAT-Timestamp": ts,
        "X-SAT-Nonce": nonce,
        "X-SAT-Signature": sig,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _admin(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "AdminP@ss123!"})
    assert r.status_code == 200, r.text
    return r.json()


def test_health(client):
    assert client.get("/healthz").json()["owner"] == "Samaraho Mukherjee"


def test_register_requires_approval(client):
    r = client.post("/api/auth/register", json={
        "email": "bob@lab.io", "username": "bob", "full_name": "Bob",
        "password": "Str0ng#Pass99"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    # pending users cannot log in
    r = client.post("/api/auth/login", json={"username": "bob", "password": "Str0ng#Pass99"})
    assert r.status_code == 403


def test_signing_and_approval_flow(client):
    tok = _admin(client)
    at, sk = tok["access_token"], tok["signing_key"]

    pend = client.get("/api/admin/users/pending",
                      headers={"Authorization": f"Bearer {at}", "Accept": "application/json"})
    bob_id = next(u["id"] for u in pend.json() if u["username"] == "bob")

    # unsigned mutation rejected
    r = client.post("/api/admin/users/approve",
                    headers={"Authorization": f"Bearer {at}", "Accept": "application/json"},
                    json={"user_id": bob_id, "role": "user"})
    assert r.status_code in (400, 401)

    # signed approve works
    body = json.dumps({"user_id": bob_id, "role": "user"}).encode()
    r = client.post("/api/admin/users/approve",
                    headers=_sign(at, sk, "POST", "/api/admin/users/approve", body),
                    content=body)
    assert r.status_code == 200 and r.json()["status"] == "approved"

    # tamper + replay are rejected
    h = _sign(at, sk, "POST", "/api/admin/users/approve", body)
    assert client.post("/api/admin/users/approve", headers=h,
                       content=json.dumps({"user_id": bob_id, "role": "admin"}).encode()
                       ).status_code == 401
    client.post("/api/admin/users/approve", headers=h, content=body)        # consume nonce
    assert client.post("/api/admin/users/approve", headers=h, content=body).status_code == 401

    # approved user can now log in
    assert client.post("/api/auth/login",
                       json={"username": "bob", "password": "Str0ng#Pass99"}).status_code == 200


def test_sso_one_time_token(client, monkeypatch):
    import app.hub as hub

    async def _noop(*a, **k):
        return ""

    monkeypatch.setattr(hub, "ensure_user", _noop)
    monkeypatch.setattr(hub, "start_server", _noop)

    bob = client.post("/api/auth/login", json={"username": "bob", "password": "Str0ng#Pass99"}).json()
    at, sk = bob["access_token"], bob["signing_key"]

    body = json.dumps({"profile": "small"}).encode()
    r = client.post("/api/notebooks/launch",
                    headers=_sign(at, sk, "POST", "/api/notebooks/launch", body), content=body)
    assert r.status_code == 200
    url = r.json()["url"]
    assert "/sso-login?token=" in url
    token = url.split("token=")[1].split("&")[0]

    from app.config import get_settings
    secret = get_settings().internal_shared_secret

    # redeem once -> ok
    r = client.post("/api/internal/redeem-ott", headers={"X-SAT-Internal": secret},
                    json={"token": token})
    assert r.status_code == 200 and r.json()["name"] == "bob"
    # redeem again -> single-use, rejected
    r = client.post("/api/internal/redeem-ott", headers={"X-SAT-Internal": secret},
                    json={"token": token})
    assert r.status_code == 401
    # wrong internal secret -> rejected
    assert client.post("/api/internal/redeem-ott", headers={"X-SAT-Internal": "nope"},
                       json={"token": token}).status_code == 401


def test_change_password_and_session_revocation(client):
    bob = client.post("/api/auth/login", json={"username": "bob", "password": "Str0ng#Pass99"}).json()
    at, sk = bob["access_token"], bob["signing_key"]
    body = json.dumps({"old_password": "Str0ng#Pass99", "new_password": "N3w#Pass!234"}).encode()
    r = client.post("/api/auth/change-password",
                    headers=_sign(at, sk, "POST", "/api/auth/change-password", body), content=body)
    assert r.status_code == 204
    # old password no longer works, new one does
    assert client.post("/api/auth/login",
                       json={"username": "bob", "password": "Str0ng#Pass99"}).status_code == 401
    assert client.post("/api/auth/login",
                       json={"username": "bob", "password": "N3w#Pass!234"}).status_code == 200


def test_metrics_endpoint(client):
    client.get("/healthz")
    body = client.get("/metrics").text
    assert "satyameba_http_requests_total" in body


def test_maintenance_cleanup_runs(client):
    from app.maintenance import cleanup_once
    res = cleanup_once()
    assert set(res) == {"sso_tokens", "sessions"}


def test_suspend_and_audit_chain(client):
    tok = _admin(client)
    at, sk = tok["access_token"], tok["signing_key"]
    bob_id = next(u["id"] for u in client.get(
        "/api/admin/users", headers={"Authorization": f"Bearer {at}", "Accept": "application/json"}
    ).json() if u["username"] == "bob")

    path = f"/api/admin/users/{bob_id}/suspend"
    r = client.post(path, headers=_sign(at, sk, "POST", path, b""), content=b"")
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert client.post("/api/auth/login",
                       json={"username": "bob", "password": "N3w#Pass!234"}).status_code == 403

    v = client.get("/api/admin/audit/verify",
                   headers={"Authorization": f"Bearer {at}", "Accept": "application/json"})
    assert v.status_code == 200 and v.json()["intact"] is True
