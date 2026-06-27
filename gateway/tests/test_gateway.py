"""End-to-end gateway tests.

Each test creates its own user (via the `admin` fixture + `make_user`) so the
suite is order-independent. Covers onboarding, request signing, SSO, 2FA, admin
recovery (reset 2FA / password / delete), forced password change, and the audit
chain.
"""
import json
import secrets
import time

import pytest

from app.security import sign_request

ADMIN_BOOT_PW = "AdminP@ss123!"
ADMIN_PW = "AdminNew#9Pass!"
USER_PW = "Str0ng#Pass99"


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


def _hdr(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


@pytest.fixture(scope="session")
def admin(client):
    """Logged-in admin with the forced password change already cleared."""
    t = client.post("/api/auth/login",
                    json={"username": "admin", "password": ADMIN_BOOT_PW}).json()
    # bootstrap admin starts with must_change_password -> change it first
    body = json.dumps({"old_password": ADMIN_BOOT_PW, "new_password": ADMIN_PW}).encode()
    r = client.post("/api/auth/change-password",
                    headers=_sign(t["access_token"], t["signing_key"],
                                  "POST", "/api/auth/change-password", body), content=body)
    assert r.status_code == 204, r.text
    return client.post("/api/auth/login",
                       json={"username": "admin", "password": ADMIN_PW}).json()


def make_user(client, admin, username, password=USER_PW, role="user"):
    client.post("/api/auth/register", json={
        "email": f"{username}@lab.io", "username": username,
        "full_name": username.title(), "password": password})
    uid = next(u["id"] for u in client.get("/api/admin/users", headers=_hdr(admin["access_token"])).json()
               if u["username"] == username)
    body = json.dumps({"user_id": uid, "role": role}).encode()
    r = client.post("/api/admin/users/approve",
                    headers=_sign(admin["access_token"], admin["signing_key"],
                                  "POST", "/api/admin/users/approve", body), content=body)
    assert r.status_code == 200, r.text
    return uid


def login(client, username, password=USER_PW, otp=None):
    body = {"username": username, "password": password}
    if otp:
        body["otp"] = otp
    return client.post("/api/auth/login", json=body)


# --------------------------------------------------------------------------- #
def test_health(client):
    j = client.get("/healthz").json()
    assert j == {"status": "ok"}            # no owner/project disclosure


def test_register_requires_approval(client):
    r = client.post("/api/auth/register", json={
        "email": "pend@lab.io", "username": "pend", "password": USER_PW})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert login(client, "pend").status_code == 403


def test_signing_replay_and_tamper(client, admin):
    uid = make_user(client, admin, "signee")
    at, sk = admin["access_token"], admin["signing_key"]
    path = f"/api/admin/users/{uid}/suspend"

    # unsigned mutation rejected
    assert client.post(path, headers=_hdr(at), content=b"").status_code in (400, 401)
    # signed ok, then the same nonce is a replay
    h = _sign(at, sk, "POST", path, b"")
    assert client.post(path, headers=h, content=b"").status_code == 200
    assert client.post(path, headers=h, content=b"").status_code == 401


def test_two_factor_login(client, admin):
    import pyotp
    make_user(client, admin, "twofa")
    c = login(client, "twofa").json()
    cat, csk = c["access_token"], c["signing_key"]
    r = client.post("/api/auth/2fa/setup",
                    headers=_sign(cat, csk, "POST", "/api/auth/2fa/setup", b""), content=b"")
    assert r.status_code == 200 and r.json()["qr_png_data_uri"].startswith("data:image/png;base64,")
    secret = r.json()["secret"]
    eb = json.dumps({"code": pyotp.TOTP(secret).now()}).encode()
    assert client.post("/api/auth/2fa/enable",
                       headers=_sign(cat, csk, "POST", "/api/auth/2fa/enable", eb),
                       content=eb).status_code == 204
    assert login(client, "twofa").json()["detail"] == "otp_required"
    assert login(client, "twofa", otp=pyotp.TOTP(secret).now()).status_code == 200


def test_change_password_revokes_sessions(client, admin):
    make_user(client, admin, "chpw")
    c = login(client, "chpw").json()
    body = json.dumps({"old_password": USER_PW, "new_password": "N3w#Pass!234"}).encode()
    assert client.post("/api/auth/change-password",
                       headers=_sign(c["access_token"], c["signing_key"],
                                     "POST", "/api/auth/change-password", body),
                       content=body).status_code == 204
    assert login(client, "chpw", "Str0ng#Pass99").status_code == 401
    assert login(client, "chpw", "N3w#Pass!234").status_code == 200


def test_admin_recovery_and_forced_change(client, admin, monkeypatch):
    import app.hub as hub

    async def _empty(*a, **k):
        return []

    monkeypatch.setattr(hub, "list_active", _empty)   # no real Hub in tests
    uid = make_user(client, admin, "recover")
    at, sk = admin["access_token"], admin["signing_key"]

    # admin resets the password -> temp password + must_change
    rp = f"/api/admin/users/{uid}/reset-password"
    r = client.post(rp, headers=_sign(at, sk, "POST", rp, b""), content=b"")
    assert r.status_code == 200
    temp = r.json()["temporary_password"]

    # user logs in with temp pw; /me works but protected routes are blocked
    c = login(client, "recover", temp).json()
    tok = c["access_token"]
    assert client.get("/api/auth/me", headers=_hdr(tok)).json()["must_change_password"] is True
    assert client.get("/api/notebooks/status", headers=_hdr(tok)).status_code == 403  # gated

    # after changing the password the gate lifts
    body = json.dumps({"old_password": temp, "new_password": "Aft3r#Reset!9"}).encode()
    assert client.post("/api/auth/change-password",
                       headers=_sign(tok, c["signing_key"], "POST", "/api/auth/change-password", body),
                       content=body).status_code == 204
    c2 = login(client, "recover", "Aft3r#Reset!9").json()
    assert client.get("/api/notebooks/status", headers=_hdr(c2["access_token"])).status_code == 200

    # reset-2fa is callable and audited
    r2 = f"/api/admin/users/{uid}/reset-2fa"
    assert client.post(r2, headers=_sign(at, sk, "POST", r2, b""), content=b"").status_code == 200


def test_delete_user(client, admin):
    uid = make_user(client, admin, "deleteme")
    at, sk = admin["access_token"], admin["signing_key"]
    path = f"/api/admin/users/{uid}"
    assert client.request("DELETE", path, headers=_sign(at, sk, "DELETE", path, b""),
                          content=b"").status_code == 204
    assert login(client, "deleteme").status_code == 401  # gone


def test_audit_chain_intact(client, admin):
    v = client.get("/api/admin/audit/verify", headers=_hdr(admin["access_token"]))
    assert v.status_code == 200 and v.json()["intact"] is True


def test_owner_is_protected(client, admin):
    at, sk = admin["access_token"], admin["signing_key"]
    me = client.get("/api/auth/me", headers=_hdr(at)).json()
    assert me["role"] == "owner"
    oid = me["id"]
    # owner cannot be suspended or deleted by anyone
    sp = f"/api/admin/users/{oid}/suspend"
    assert client.post(sp, headers=_sign(at, sk, "POST", sp, b""), content=b"").status_code == 403
    dp = f"/api/admin/users/{oid}"
    assert client.request("DELETE", dp, headers=_sign(at, sk, "DELETE", dp, b""),
                          content=b"").status_code == 403
    # nobody can be promoted to owner
    uid = make_user(client, admin, "wannabe")
    body = json.dumps({"user_id": uid, "role": "owner"}).encode()
    assert client.post("/api/admin/users/approve",
                       headers=_sign(at, sk, "POST", "/api/admin/users/approve", body),
                       content=body).status_code == 403


def test_boost_request_approve_and_schedule(client, admin, monkeypatch):
    import app.hub as hub

    async def _noop(*a, **k):
        return None

    async def _empty(*a, **k):
        return []

    monkeypatch.setattr(hub, "ensure_user", _noop)
    monkeypatch.setattr(hub, "start_server", _noop)
    monkeypatch.setattr(hub, "stop_server", _noop)
    monkeypatch.setattr(hub, "list_active", _empty)

    make_user(client, admin, "booster")
    c = login(client, "booster").json()
    at, sk = c["access_token"], c["signing_key"]

    # user asks for a boost
    rb = json.dumps({"gpus": 3, "reason": "training run"}).encode()
    r = client.post("/api/notebooks/boost/request",
                    headers=_sign(at, sk, "POST", "/api/notebooks/boost/request", rb), content=rb)
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    assert r.json()["status"] == "pending"

    # admin sees it pending and approves (adjusting to 2)
    boosts = client.get("/api/admin/boosts", headers=_hdr(admin["access_token"])).json()
    assert any(b["id"] == bid for b in boosts)
    ab = json.dumps({"gpus": 2}).encode()
    ap = f"/api/admin/boosts/{bid}/approve"
    r = client.post(ap, headers=_sign(admin["access_token"], admin["signing_key"], "POST", ap, ab),
                    content=ab)
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["gpus"] == 2

    # user is notified
    notes = client.get("/api/notebooks/notifications", headers=_hdr(at)).json()
    assert any("approv" in n["message"].lower() for n in notes)

    # launching consumes the one-session grant and reports boost mode
    lb = json.dumps({"profile": "gpu"}).encode()
    r = client.post("/api/notebooks/launch",
                    headers=_sign(at, sk, "POST", "/api/notebooks/launch", lb), content=lb)
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "boost"
    assert client.get("/api/notebooks/boost/mine", headers=_hdr(at)).json()["status"] == "consumed"

    # cluster status now shows an active run for this user
    cl = client.get("/api/notebooks/cluster", headers=_hdr(at)).json()
    assert cl["you"]["active"] is True


def test_node_drain_and_activate(client, admin):
    from app.security import internal_token

    host = "worker-drain-1"
    tok = internal_token(host)
    reg = client.post("/api/nodes/register",
                      headers={"X-SAT-Node-Token": tok},
                      json={"hostname": host, "ip": "10.0.0.9", "role": "worker",
                            "labels": {"gpu": "rtx5070"}})
    assert reg.status_code == 200, reg.text
    nid = reg.json()["id"]

    at, sk = admin["access_token"], admin["signing_key"]
    dp = f"/api/admin/nodes/{nid}/drain"
    r = client.post(dp, headers=_sign(at, sk, "POST", dp, b""), content=b"")
    assert r.status_code == 200 and r.json()["status"] == "draining"
    ap = f"/api/admin/nodes/{nid}/activate"
    r = client.post(ap, headers=_sign(at, sk, "POST", ap, b""), content=b"")
    assert r.status_code == 200 and r.json()["status"] == "online"


def test_audit_csv_export(client, admin):
    r = client.get("/api/admin/audit/export.csv", headers=_hdr(admin["access_token"]))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.splitlines()[0] == "id,timestamp,actor,action,target,ip,detail"


def test_metrics_endpoint(client):
    client.get("/healthz")
    assert "satyameba_http_requests_total" in client.get("/metrics").text


def test_maintenance_cleanup_runs(client):
    from app.maintenance import cleanup_once
    assert set(cleanup_once()) == {"sso_tokens", "sessions", "audit"}


def test_production_fail_closed():
    from types import SimpleNamespace

    import pytest

    from app.main import _assert_production_secrets

    def s(**kw):
        base = dict(jwt_algorithm="RS256", jwt_private_key="K", jwt_public_key="K",
                    jwt_secret="strong", internal_shared_secret="strong")
        base.update(kw)
        ns = SimpleNamespace(**base)
        ns.is_production = True
        return ns

    # properly configured RS256 -> OK
    _assert_production_secrets(s())
    # RS256 selected but keypair missing -> refuse
    with pytest.raises(RuntimeError):
        _assert_production_secrets(s(jwt_private_key="", jwt_public_key=""))
    # default HS256 secret while HS256 is effective -> refuse
    with pytest.raises(RuntimeError):
        _assert_production_secrets(s(jwt_algorithm="HS256", jwt_secret="CHANGE_ME_x"))
    # default internal secret -> refuse
    with pytest.raises(RuntimeError):
        _assert_production_secrets(s(internal_shared_secret="CHANGE_ME_internal"))
    # non-production never blocks
    ns = s(jwt_private_key="")
    ns.is_production = False
    _assert_production_secrets(ns)
