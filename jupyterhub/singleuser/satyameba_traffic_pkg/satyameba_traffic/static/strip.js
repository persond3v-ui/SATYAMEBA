/* SATYAMEBA in-Lab traffic strip — vanilla JS, no framework.
 *
 * Polls the same-origin proxy /satyameba/api/traffic (the server extension adds
 * the read-only token) and renders a floating strip: your node, a colour-coded
 * status light (idle / exclusive / shared / boost), how many people share your
 * node, cluster busy-ness, and a "Request more GPUs" button that jumps to the
 * SATYAMEBA workspace. Live GPU/VRAM/RAM/CPU are shown by jupyter-resource-usage
 * and jupyterlab-nvdashboard; this strip adds the SATYAMEBA-specific signal.
 */
(function () {
  if (window.__satyameba_strip__) return;
  window.__satyameba_strip__ = true;

  function el(id) { return document.getElementById(id); }
  function ensure() {
    let s = el("satyameba-strip");
    if (s) return s;
    s = document.createElement("div");
    s.id = "satyameba-strip";
    s.innerHTML =
      '<span class="dot idle" id="sat-dot"></span>' +
      '<span class="sat-metric" id="sat-where">connecting…</span>' +
      '<button id="sat-boost" title="Ask an admin for multi-GPU power">⚡ More GPUs</button>';
    document.body.appendChild(s);
    el("sat-boost").onclick = function () {
      // Jump to the workspace (where the user is authenticated) to request a boost.
      window.open("/#/app?boost=1", "_blank", "noopener");
    };
    return s;
  }

  function render(d) {
    ensure();
    const dot = el("sat-dot"), where = el("sat-where");
    if (!d || d.unavailable) { where.textContent = "cluster: offline"; return; }
    const you = d.you || {};
    const status = you.status || "idle";
    dot.className = "dot " + status;
    let txt = "";
    if (!you.active) {
      txt = `cluster idle · ${d.active_users || 0}/${d.total_nodes || 0} nodes busy`;
    } else if (status === "boost") {
      txt = `BOOST · ${you.gpus} GPU node(s) · all yours`;
    } else if (status === "shared") {
      txt = `${you.node} · sharing with ${you.sharing_with} (concurrent)`;
    } else {
      txt = `${you.node} · whole node · exclusive`;
    }
    where.textContent = txt + ` · ${d.active_users || 0}/${d.total_nodes || 0} active`;
  }

  async function poll() {
    try {
      const base = (document.body.dataset.baseUrl || "/");
      const r = await fetch(base.replace(/\/$/, "") + "/satyameba/api/traffic",
                            { headers: { Accept: "application/json" } });
      render(await r.json());
    } catch (e) { render({ unavailable: true }); }
  }

  function start() { ensure(); poll(); setInterval(poll, 5000); }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else { start(); }
})();
