// SATYAMEBA API client.
//
// Responsibilities:
//   * store the access/refresh tokens + per-session HMAC signing key
//   * sign every state-changing request (POST/PUT/PATCH/DELETE) with
//     HMAC-SHA256 over canonical(method, path, timestamp, nonce, sha256(body))
//   * transparently refresh an expired access token once
//
// The signing key never leaves the browser and is only held in memory +
// sessionStorage; combined with the server-side timestamp/nonce checks this
// kills request tampering and replay.

const SIGNED_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const store = {
  get access() { return sessionStorage.getItem("sat_access") || ""; },
  set access(v) { v ? sessionStorage.setItem("sat_access", v) : sessionStorage.removeItem("sat_access"); },
  get refresh() { return sessionStorage.getItem("sat_refresh") || ""; },
  set refresh(v) { v ? sessionStorage.setItem("sat_refresh", v) : sessionStorage.removeItem("sat_refresh"); },
  get signingKey() { return sessionStorage.getItem("sat_skey") || ""; },
  set signingKey(v) { v ? sessionStorage.setItem("sat_skey", v) : sessionStorage.removeItem("sat_skey"); },
};

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
function hexToBytes(h) {
  const out = new Uint8Array(h.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
  return out;
}
async function sha256Hex(str) {
  const data = new TextEncoder().encode(str || "");
  return hex(await crypto.subtle.digest("SHA-256", data));
}
async function hmacHex(keyHex, message) {
  const key = await crypto.subtle.importKey(
    "raw", hexToBytes(keyHex), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return hex(sig);
}
function nonce() {
  const a = new Uint8Array(16);
  crypto.getRandomValues(a);
  return hex(a.buffer);
}

async function signedHeaders(method, path, bodyString) {
  if (!SIGNED_METHODS.has(method) || !store.signingKey) return {};
  const ts = Math.floor(Date.now() / 1000).toString();
  const n = nonce();
  const bodyHash = await sha256Hex(bodyString || "");
  const canonical = [method.toUpperCase(), path, ts, n, bodyHash].join("\n");
  const sig = await hmacHex(store.signingKey, canonical);
  return { "X-SAT-Timestamp": ts, "X-SAT-Nonce": n, "X-SAT-Signature": sig };
}

async function request(method, path, body, _retried) {
  const bodyString = body === undefined ? undefined : JSON.stringify(body);
  const headers = {
    Accept: "application/json",
    ...(bodyString !== undefined ? { "Content-Type": "application/json" } : {}),
    ...(store.access ? { Authorization: `Bearer ${store.access}` } : {}),
    ...(await signedHeaders(method, path, bodyString)),
  };
  const res = await fetch(path, { method, headers, body: bodyString });

  if (res.status === 401 && store.refresh && !_retried && !path.endsWith("/refresh")) {
    const ok = await tryRefresh();
    if (ok) return request(method, path, body, true);
  }
  let data = null;
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) {
    const msg = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

async function tryRefresh() {
  try {
    const res = await fetch("/api/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refresh_token: store.refresh }),
    });
    if (!res.ok) return false;
    const t = await res.json();
    store.access = t.access_token;
    store.refresh = t.refresh_token;
    store.signingKey = t.signing_key;
    return true;
  } catch (_) {
    return false;
  }
}

export const api = {
  isAuthed: () => !!store.access,
  saveTokens(t) {
    store.access = t.access_token;
    store.refresh = t.refresh_token;
    store.signingKey = t.signing_key;
  },
  clear() { store.access = ""; store.refresh = ""; store.signingKey = ""; },

  register: (p) => request("POST", "/api/auth/register", p),
  login: (p) => request("POST", "/api/auth/login", p),
  logout: () => request("POST", "/api/auth/logout"),
  me: () => request("GET", "/api/auth/me"),
  changePassword: (old_password, new_password) =>
    request("POST", "/api/auth/change-password", { old_password, new_password }),
  twofaSetup: () => request("POST", "/api/auth/2fa/setup"),
  twofaEnable: (code) => request("POST", "/api/auth/2fa/enable", { code }),
  twofaDisable: (code) => request("POST", "/api/auth/2fa/disable", { code }),

  launch: (profile = "medium") => request("POST", "/api/notebooks/launch", { profile }),
  stopNotebook: () => request("POST", "/api/notebooks/stop"),
  notebookStatus: () => request("GET", "/api/notebooks/status"),
  cluster: () => request("GET", "/api/notebooks/cluster"),
  resources: () => request("GET", "/api/notebooks/resources"),
  requestBoost: (gpus, reason) => request("POST", "/api/notebooks/boost/request", { gpus, reason }),
  myBoost: () => request("GET", "/api/notebooks/boost/mine"),
  notifications: () => request("GET", "/api/notebooks/notifications"),
  readNotifications: () => request("POST", "/api/notebooks/notifications/read"),
  myLogs: (q = "") => request("GET", `/api/auth/me/logs${q ? `?q=${encodeURIComponent(q)}` : ""}`),

  // admin
  stats: () => request("GET", "/api/admin/stats"),
  pending: () => request("GET", "/api/admin/users/pending"),
  users: (status) => request("GET", `/api/admin/users${status ? `?status=${status}` : ""}`),
  approve: (user_id, role = "user") => request("POST", "/api/admin/users/approve", { user_id, role }),
  reject: (user_id, reason = "") => request("POST", "/api/admin/users/reject", { user_id, reason }),
  suspend: (user_id) => request("POST", `/api/admin/users/${user_id}/suspend`),
  reinstate: (user_id) => request("POST", `/api/admin/users/${user_id}/reinstate`),
  reset2fa: (user_id) => request("POST", `/api/admin/users/${user_id}/reset-2fa`),
  resetPassword: (user_id) => request("POST", `/api/admin/users/${user_id}/reset-password`),
  deleteUser: (user_id) => request("DELETE", `/api/admin/users/${user_id}`),
  nodes: () => request("GET", "/api/admin/nodes"),
  drainNode: (id) => request("POST", `/api/admin/nodes/${id}/drain`),
  activateNode: (id) => request("POST", `/api/admin/nodes/${id}/activate`),
  metricsLive: () => request("GET", "/api/admin/metrics/live"),
  activeSessions: () => request("GET", "/api/admin/sessions/active"),
  boosts: (status = "pending") => request("GET", `/api/admin/boosts?status=${status}`),
  approveBoost: (id, gpus) => request("POST", `/api/admin/boosts/${id}/approve`, gpus ? { gpus } : {}),
  denyBoost: (id, reason = "") => request("POST", `/api/admin/boosts/${id}/deny`, { reason }),
  audit: (limit = 200, opts = {}) => {
    const p = new URLSearchParams({ limit });
    if (opts.q) p.set("q", opts.q);
    if (opts.username) p.set("username", opts.username);
    if (opts.action) p.set("action", opts.action);
    return request("GET", `/api/admin/audit?${p.toString()}`);
  },
  userLogs: (user_id) => request("GET", `/api/admin/users/${user_id}/logs`),
  userUsage: (user_id) => request("GET", `/api/admin/users/${user_id}/usage`),
  usersSearch: (q = "", status) => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    const s = p.toString();
    return request("GET", `/api/admin/users${s ? `?${s}` : ""}`);
  },
  setRole: (user_id, role) => request("POST", `/api/admin/users/${user_id}/role`, { role }),
  createUser: (p) => request("POST", "/api/admin/users", p),
  bulkUsers: (action, user_ids) => request("POST", "/api/admin/users/bulk", { action, user_ids }),
  setExpiry: (user_id, body) => request("POST", `/api/admin/users/${user_id}/expiry`, body),
  setQuota: (user_id, body) => request("POST", `/api/admin/users/${user_id}/quota`, body),
  setTags: (user_id, tags) => request("POST", `/api/admin/users/${user_id}/tags`, { tags }),
  invites: () => request("GET", "/api/admin/invites"),
  createInvite: (p) => request("POST", "/api/admin/invites", p),
  revokeInvite: (code) => request("POST", `/api/admin/invites/${code}/revoke`),
  attention: () => request("GET", "/api/admin/attention"),
  announce: (message, kind = "info") => request("POST", "/api/admin/announce", { message, kind }),
  getMaintenance: () => request("GET", "/api/admin/maintenance"),
  setMaintenance: (on, message = "") => request("POST", "/api/admin/maintenance", { on, message }),
  auditVerify: () => request("GET", "/api/admin/audit/verify"),
  async auditExport() {
    const res = await fetch("/api/admin/audit/export.csv", {
      headers: store.access ? { Authorization: `Bearer ${store.access}` } : {},
    });
    if (!res.ok) throw new Error(`Export failed (${res.status})`);
    return res.blob();
  },
};
