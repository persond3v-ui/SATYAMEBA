// SATYAMEBA SPA views & routing (hash-based, no build step required).
import { api } from "/src/api.js";

const view = document.getElementById("view");
const nav = document.getElementById("nav");
const toastEl = document.getElementById("toast");

let me = null; // current user
let liveTimer = null; // admin live-metrics poller

const GRAFANA_URL = window.SAT_GRAFANA_URL || "/grafana/";

function toast(msg, kind = "") {
  toastEl.textContent = msg;
  toastEl.className = `toast ${kind}`;
  setTimeout(() => (toastEl.className = "toast hidden"), 3500);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const badge = (s) => `<span class="badge ${esc(s)}">${esc(s)}</span>`;
const go = (hash) => (location.hash = hash);

function renderNav() {
  if (!me) { nav.innerHTML = `<a data-go="#/login">Sign in</a><a data-go="#/register">Register</a>`; return; }
  const adminLink = me.role === "admin" ? `<a data-go="#/admin">Admin</a>` : "";
  nav.innerHTML = `<a data-go="#/app">Workspace</a>${adminLink}<a id="logout">Logout (${esc(me.username)})</a>`;
  nav.querySelector("#logout").onclick = async () => {
    try { await api.logout(); } catch (_) {}
    api.clear(); me = null; go("#/login");
  };
}

nav.addEventListener("click", (e) => {
  const t = e.target.closest("[data-go]");
  if (t) go(t.dataset.go);
});

// ---------------------------------------------------------------- auth views
function loginView() {
  view.innerHTML = `
    <div class="card auth-card">
      <h1>Welcome back</h1>
      <p class="muted">Sign in to your SATYAMEBA workspace.</p>
      <label>Username or email</label>
      <input id="u" autocomplete="username" />
      <label>Password</label>
      <input id="p" type="password" autocomplete="current-password" />
      <div id="otpRow" class="hidden">
        <label>Authenticator code</label>
        <input id="otp" inputmode="numeric" autocomplete="one-time-code" placeholder="6-digit code" />
      </div>
      <div class="btn-row"><button id="go">Sign in</button>
        <button class="secondary" data-go="#/register">Create account</button></div>
      <div class="err" id="err"></div>
    </div>`;
  view.querySelector("[data-go]").onclick = () => go("#/register");
  view.querySelector("#go").onclick = doLogin;
  view.querySelector("#p").onkeydown = (e) => e.key === "Enter" && doLogin();
}
async function doLogin() {
  const err = view.querySelector("#err"); err.textContent = "";
  const otpEl = view.querySelector("#otp");
  try {
    const body = {
      username: view.querySelector("#u").value.trim(),
      password: view.querySelector("#p").value,
    };
    if (otpEl && otpEl.value.trim()) body.otp = otpEl.value.trim();
    const t = await api.login(body);
    api.saveTokens(t);
    me = await api.me();
    renderNav();
    go(me.role === "admin" ? "#/admin" : "#/app");
  } catch (e) {
    if (e.message === "otp_required") {
      view.querySelector("#otpRow").classList.remove("hidden");
      otpEl.focus();
      err.textContent = "Enter the 6-digit code from your authenticator app.";
    } else { err.textContent = e.message; }
  }
}

function registerView() {
  view.innerHTML = `
    <div class="card auth-card">
      <h1>Request access</h1>
      <p class="muted">New accounts are activated after an administrator approves them.</p>
      <label>Full name</label><input id="fn" />
      <label>Username</label><input id="un" placeholder="lowercase, 3–32 chars" />
      <label>Email</label><input id="em" type="email" />
      <label>Password</label><input id="pw" type="password" />
      <p class="hint">Min 10 chars, mixing 3 of: lower, upper, digit, symbol.</p>
      <div class="btn-row"><button id="go">Submit request</button>
        <button class="secondary" data-go="#/login">Back to sign in</button></div>
      <div class="err" id="err"></div>
    </div>`;
  view.querySelector("[data-go]").onclick = () => go("#/login");
  view.querySelector("#go").onclick = async () => {
    const err = view.querySelector("#err"); err.textContent = "";
    try {
      await api.register({
        full_name: view.querySelector("#fn").value.trim(),
        username: view.querySelector("#un").value.trim().toLowerCase(),
        email: view.querySelector("#em").value.trim(),
        password: view.querySelector("#pw").value,
      });
      toast("Request submitted — an admin will review it shortly.", "ok");
      go("#/login");
    } catch (e) { err.textContent = e.message; }
  };
}

function forcedChangeView() {
  view.innerHTML = `
    <div class="card auth-card">
      <h1>Set a new password</h1>
      <p class="muted">Your account must change its password before continuing.</p>
      <label>Current / temporary password</label>
      <input id="op" type="password" autocomplete="current-password" />
      <label>New password</label><input id="np" type="password" autocomplete="new-password" />
      <p class="hint">Min 10 chars, mixing 3 of: lower, upper, digit, symbol.</p>
      <div class="btn-row"><button id="go">Update password</button></div>
      <div class="err" id="err"></div>
    </div>`;
  view.querySelector("#go").onclick = async () => {
    const err = view.querySelector("#err"); err.textContent = "";
    try {
      await api.changePassword(view.querySelector("#op").value, view.querySelector("#np").value);
      toast("Password updated", "ok");
      me = await api.me();
      go(me.role === "admin" ? "#/admin" : "#/app");
    } catch (e) { err.textContent = e.message; }
  };
}

// ------------------------------------------------------------- user workspace
async function workspaceView() {
  view.innerHTML = `
    <div class="card launch-hero">
      <div class="muted">Hello ${esc(me.full_name || me.username)}</div>
      <div class="big">Your private notebook environment</div>
      <p class="muted">Spin up an isolated JupyterLab on the cluster. Your work is
         saved in a private volume that follows your account; shared datasets live
         in <code>/home/jovyan/shared</code>.</p>
      <div style="max-width:320px;margin:0 auto">
        <label>Resource profile</label>
        <select id="profile">
          <option value="small">Small · 2 GB · 1 CPU</option>
          <option value="medium" selected>Medium · 4 GB · 2 CPU</option>
          <option value="large">Large · 8 GB · 4 CPU</option>
          <option value="gpu">GPU · 8 GB · 4 CPU · 1 GPU</option>
        </select>
      </div>
      <div class="btn-row" style="justify-content:center">
        <button id="launch">🚀 Launch notebook (new tab)</button>
        <button class="secondary" id="stop">Stop server</button>
      </div>
      <p class="hint" id="state"></p>
    </div>

    ${me.must_change_password ? `<div class="card" style="border-color:var(--warn)">
      ⚠️ <strong>Please change your password.</strong> This account is still using its
      initial password — set a new one below.</div>` : ""}

    <div class="card" style="max-width:420px">
      <h2>Change password</h2>
      <label>Current password</label><input id="op" type="password" autocomplete="current-password" />
      <label>New password</label><input id="np" type="password" autocomplete="new-password" />
      <p class="hint">Min 10 chars, mixing 3 of: lower, upper, digit, symbol.</p>
      <div class="btn-row"><button class="secondary" id="chpw">Update password</button></div>
    </div>

    <div class="card" style="max-width:420px" id="twofa">
      <h2>Two-factor authentication ${me.totp_enabled ? badge("approved") : ""}</h2>
      <div id="twofaBody"></div>
    </div>`;
  const state = view.querySelector("#state");
  refreshNbStatus(state);
  view.querySelector("#launch").onclick = async () => {
    const profile = view.querySelector("#profile").value;
    state.textContent = "Starting your server… opening in a new tab (first launch can take a moment).";
    try {
      const r = await api.launch(profile);
      window.open(r.url, "_blank", "noopener");
      state.textContent = "Server starting — switch to the new tab for JupyterLab.";
    } catch (e) { toast(e.message, "bad"); state.textContent = e.message; }
  };
  view.querySelector("#stop").onclick = async () => {
    try { await api.stopNotebook(); toast("Server stopped", "ok"); refreshNbStatus(state); }
    catch (e) { toast(e.message, "bad"); }
  };
  view.querySelector("#chpw").onclick = async () => {
    try {
      await api.changePassword(view.querySelector("#op").value, view.querySelector("#np").value);
      toast("Password updated", "ok");
      me = await api.me();
      workspaceView();
    } catch (e) { toast(e.message, "bad"); }
  };
  render2FA();
}

function render2FA() {
  const body = view.querySelector("#twofaBody");
  if (!body) return;
  if (me.totp_enabled) {
    body.innerHTML = `<p class="muted">2FA is on. Disabling requires a current code.</p>
      <label>Authenticator code</label><input id="dcode" inputmode="numeric" placeholder="6-digit code" />
      <div class="btn-row"><button class="danger" id="disable2fa">Disable 2FA</button></div>`;
    body.querySelector("#disable2fa").onclick = async () => {
      try {
        await api.twofaDisable(body.querySelector("#dcode").value.trim());
        toast("2FA disabled", "ok"); me = await api.me(); workspaceView();
      } catch (e) { toast(e.message, "bad"); }
    };
    return;
  }
  body.innerHTML = `<p class="muted">Protect your account with a TOTP app
      (Google Authenticator, Aegis, 1Password…).</p>
    <div class="btn-row"><button class="secondary" id="setup2fa">Set up 2FA</button></div>
    <div id="enroll" class="hidden"></div>`;
  body.querySelector("#setup2fa").onclick = async () => {
    try {
      const s = await api.twofaSetup();
      const enroll = body.querySelector("#enroll");
      enroll.classList.remove("hidden");
      enroll.innerHTML = `<p class="muted">Scan this, then enter a code to confirm:</p>
        <img alt="2FA QR" src="${esc(s.qr_png_data_uri)}" style="background:#fff;padding:8px;border-radius:8px" />
        <p class="hint">Manual key: <code>${esc(s.secret)}</code></p>
        <label>Code from app</label><input id="ecode" inputmode="numeric" placeholder="6-digit code" />
        <div class="btn-row"><button class="ok" id="enable2fa">Confirm & enable</button></div>`;
      enroll.querySelector("#enable2fa").onclick = async () => {
        try {
          await api.twofaEnable(enroll.querySelector("#ecode").value.trim());
          toast("2FA enabled", "ok"); me = await api.me(); workspaceView();
        } catch (e) { toast(e.message, "bad"); }
      };
    } catch (e) { toast(e.message, "bad"); }
  };
}
async function refreshNbStatus(el) {
  try { const s = await api.notebookStatus(); el.textContent = s.active ? "A server is currently running." : "No server running."; }
  catch (_) {}
}

// --------------------------------------------------------------- admin views
const adminTabs = ["Overview", "Approvals", "Users", "Nodes", "Sessions", "Monitoring", "Audit"];
async function adminView(tab = "Overview") {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  view.innerHTML = `
    <h1>Admin control plane</h1>
    <div class="tabs" id="tabs"></div>
    <div id="panel"></div>`;
  const tabsEl = view.querySelector("#tabs");
  adminTabs.forEach((t) => {
    const b = document.createElement("button");
    b.textContent = t; b.className = t === tab ? "active" : "";
    b.onclick = () => go(`#/admin/${t.toLowerCase()}`);
    tabsEl.appendChild(b);
  });
  const panel = view.querySelector("#panel");
  panel.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    if (tab === "Overview") await renderOverview(panel);
    else if (tab === "Approvals") await renderApprovals(panel);
    else if (tab === "Users") await renderUsers(panel);
    else if (tab === "Nodes") await renderNodes(panel);
    else if (tab === "Sessions") await renderSessions(panel);
    else if (tab === "Monitoring") renderMonitoring(panel);
    else if (tab === "Audit") await renderAudit(panel);
  } catch (e) {
    if (e.message === "admin_2fa_required") {
      panel.innerHTML = `<div class="card" style="border-color:var(--warn)">
        🔒 <strong>Two-factor authentication is required for admins.</strong>
        <p class="muted">Enable 2FA in your workspace, then return here.</p>
        <div class="btn-row"><button id="to2fa">Go to workspace</button></div></div>`;
      panel.querySelector("#to2fa").onclick = () => go("#/app");
    } else {
      panel.innerHTML = `<div class="err">${esc(e.message)}</div>`;
    }
  }
}

async function renderOverview(p) {
  const s = await api.stats();
  const u = s.users || {};
  p.innerHTML = `<div class="grid">
    <div class="stat"><div class="n">${u.pending || 0}</div><div class="l">Pending</div></div>
    <div class="stat"><div class="n">${u.approved || 0}</div><div class="l">Approved</div></div>
    <div class="stat"><div class="n">${u.suspended || 0}</div><div class="l">Suspended</div></div>
    <div class="stat"><div class="n">${s.nodes || 0}</div><div class="l">Cluster nodes</div></div>
  </div>

  <div class="card" style="margin-top:18px">
    <h2>Live cluster <span class="muted" style="font-size:.8rem">· direct from Prometheus, refreshing</span></h2>
    <div class="grid" id="live">
      <div class="stat"><div class="n" id="m_cpu">—</div><div class="l">CPU busy %</div></div>
      <div class="stat"><div class="n" id="m_mem">—</div><div class="l">Memory used %</div></div>
      <div class="stat"><div class="n" id="m_disk">—</div><div class="l">Disk used %</div></div>
      <div class="stat"><div class="n" id="m_gpu">—</div><div class="l">GPU util %</div></div>
      <div class="stat"><div class="n" id="m_net">—</div><div class="l">Net RX MB/s</div></div>
      <div class="stat"><div class="n" id="m_up">—</div><div class="l">Targets up</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Audit chain integrity</h2>
    <p class="muted" id="chain">checking…</p>
  </div>`;

  const fmt = (v, d = 1) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));
  async function pollLive() {
    try {
      const m = await api.metricsLive();
      const set = (id, v) => { const el = p.querySelector(id); if (el) el.textContent = v; };
      set("#m_cpu", fmt(m.cpu_busy));
      set("#m_mem", fmt(m.mem_used));
      set("#m_disk", fmt(m.disk_used));
      set("#m_gpu", m.gpu_util === null ? "n/a" : fmt(m.gpu_util));
      set("#m_net", m.net_rx === null ? "—" : fmt(m.net_rx / 1e6, 2));
      set("#m_up", m.nodes_up === null ? "—" : fmt(m.nodes_up, 0));
    } catch (_) {}
  }
  pollLive();
  liveTimer = setInterval(pollLive, 10000);

  try {
    const v = await api.auditVerify();
    p.querySelector("#chain").innerHTML = v.intact
      ? `${badge("approved")} Tamper-evident log intact.`
      : `${badge("suspended")} Chain broken at entry #${v.first_tampered_id} — investigate.`;
  } catch (_) {}
}

async function renderApprovals(p) {
  const list = await api.pending();
  if (!list.length) { p.innerHTML = `<div class="card">No pending requests. 🎉</div>`; return; }
  p.innerHTML = `<div class="card"><table><thead><tr>
    <th>User</th><th>Email</th><th>Requested</th><th>Grant role</th><th>Action</th>
    </tr></thead><tbody>${list.map(rowFor).join("")}</tbody></table></div>`;
  function rowFor(u) {
    return `<tr data-id="${u.id}">
      <td><strong>${esc(u.username)}</strong><br><span class="muted">${esc(u.full_name)}</span></td>
      <td>${esc(u.email)}</td>
      <td class="muted">${new Date(u.created_at).toLocaleString()}</td>
      <td><select class="role"><option value="user">user</option><option value="admin">admin</option></select></td>
      <td><button class="ok approve">Approve</button> <button class="danger reject">Reject</button></td>
    </tr>`;
  }
  p.querySelectorAll("tr[data-id]").forEach((tr) => {
    const id = tr.dataset.id;
    tr.querySelector(".approve").onclick = async () => {
      try { await api.approve(id, tr.querySelector(".role").value); toast("Approved", "ok"); adminView("Approvals"); }
      catch (e) { toast(e.message, "bad"); }
    };
    tr.querySelector(".reject").onclick = async () => {
      try { await api.reject(id); toast("Rejected", "ok"); adminView("Approvals"); }
      catch (e) { toast(e.message, "bad"); }
    };
  });
}

async function renderUsers(p) {
  const list = await api.users();
  p.innerHTML = `<div class="card"><table><thead><tr>
    <th>User</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th>Action</th>
    </tr></thead><tbody>${list.map(rowFor).join("")}</tbody></table></div>`;
  function rowFor(u) {
    if (u.username === me.username) {
      var act = '<span class="muted">you</span>';
    } else {
      const susp = u.status === "suspended"
        ? `<button class="ok reinstate">Reinstate</button>`
        : `<button class="danger suspend">Kick off</button>`;
      var act = `${susp}
        <button class="secondary reset2fa">Reset 2FA</button>
        <button class="secondary resetpw">Reset PW</button>
        <button class="danger del">Delete</button>`;
    }
    const twofa = u.totp_enabled ? ' 🔒' : '';
    return `<tr data-id="${u.id}">
      <td><strong>${esc(u.username)}</strong>${twofa}</td><td>${esc(u.email)}</td>
      <td>${esc(u.role)}</td><td>${badge(u.status)}</td>
      <td class="muted">${u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}</td>
      <td>${act}</td></tr>`;
  }
  p.querySelectorAll("tr[data-id]").forEach((tr) => {
    const id = tr.dataset.id;
    const on = (sel, fn) => { const b = tr.querySelector(sel); if (b) b.onclick = fn; };
    const refresh = () => adminView("Users");
    on(".suspend", async () => { try { await api.suspend(id); toast("User kicked off", "ok"); refresh(); } catch (e) { toast(e.message, "bad"); } });
    on(".reinstate", async () => { try { await api.reinstate(id); toast("Reinstated", "ok"); refresh(); } catch (e) { toast(e.message, "bad"); } });
    on(".reset2fa", async () => { if (!confirm("Reset this user's 2FA? They'll re-enrol on next login.")) return; try { await api.reset2fa(id); toast("2FA reset", "ok"); refresh(); } catch (e) { toast(e.message, "bad"); } });
    on(".resetpw", async () => {
      if (!confirm("Reset this user's password to a temporary one?")) return;
      try { const r = await api.resetPassword(id); window.prompt("Temporary password (relay securely; user must change it on next login):", r.temporary_password); refresh(); }
      catch (e) { toast(e.message, "bad"); }
    });
    on(".del", async () => { if (!confirm("Permanently delete this user and their notebook? This cannot be undone.")) return; try { await api.deleteUser(id); toast("User deleted", "ok"); refresh(); } catch (e) { toast(e.message, "bad"); } });
  });
}

async function renderNodes(p) {
  const list = await api.nodes();
  if (!list.length) { p.innerHTML = `<div class="card">No nodes registered yet. Run the worker join script on each machine.</div>`; return; }
  p.innerHTML = `<div class="card"><table><thead><tr>
    <th>Host</th><th>IP</th><th>Role</th><th>Status</th><th>GPU</th><th>Last heartbeat</th>
    </tr></thead><tbody>${list.map((n) => `<tr>
      <td><strong>${esc(n.hostname)}</strong></td><td>${esc(n.ip)}</td>
      <td>${esc(n.role)}</td><td>${badge(n.status)}</td>
      <td>${n.labels && n.labels.gpu ? esc(n.labels.gpu) : "—"}</td>
      <td class="muted">${n.last_heartbeat ? new Date(n.last_heartbeat).toLocaleString() : "—"}</td>
    </tr>`).join("")}</tbody></table></div>`;
}

async function renderSessions(p) {
  const list = await api.activeSessions();
  const active = list.filter((s) => s.active);
  p.innerHTML = `<div class="card"><h2>Running notebooks (${active.length})</h2>
    <table><thead><tr><th>User</th><th>Active</th><th>Last activity</th></tr></thead>
    <tbody>${list.map((s) => `<tr><td>${esc(s.username)}</td>
      <td>${s.active ? badge("online") : badge("offline")}</td>
      <td class="muted">${s.last_activity ? new Date(s.last_activity).toLocaleString() : "—"}</td></tr>`).join("")}
    </tbody></table></div>`;
}

function renderMonitoring(p) {
  p.innerHTML = `<div class="card">
    <h2>Cluster metrics</h2>
    <p class="muted">Live CPU / GPU / network / storage per node, served by Grafana
       (backed by Prometheus + node-exporter + cAdvisor + DCGM).</p>
    <iframe class="monitor-frame" src="${esc(GRAFANA_URL)}" title="grafana"></iframe>
  </div>`;
}

async function renderAudit(p) {
  const list = await api.audit(200);
  p.innerHTML = `<div class="card"><h2>Audit log</h2>
    <table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>IP</th></tr></thead>
    <tbody>${list.map((a) => `<tr>
      <td class="muted">${new Date(a.timestamp).toLocaleString()}</td>
      <td>${esc(a.actor_label)}</td><td>${esc(a.action)}</td>
      <td>${esc(a.target)}</td><td class="muted">${esc(a.ip)}</td></tr>`).join("")}
    </tbody></table></div>`;
}

// ------------------------------------------------------------------- router
async function bootstrapMe() {
  if (api.isAuthed() && !me) {
    try { me = await api.me(); } catch (_) { api.clear(); me = null; }
  }
}
async function route() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
  await bootstrapMe();
  renderNav();
  const hash = location.hash || (me ? "#/app" : "#/login");

  if (hash.startsWith("#/register")) return registerView();
  if (hash.startsWith("#/login")) return me ? go("#/app") : loginView();

  if (!me) return go("#/login");

  // Forced password change blocks everything else until done.
  if (me.must_change_password) return forcedChangeView();

  if (hash.startsWith("#/admin")) {
    if (me.role !== "admin") return go("#/app");
    const tab = hash.split("/")[2];
    const nice = adminTabs.find((t) => t.toLowerCase() === tab) || "Overview";
    return adminView(nice);
  }
  return workspaceView();
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
route();
