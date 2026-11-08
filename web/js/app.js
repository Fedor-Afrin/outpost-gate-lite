// ---------------------------------------------------------------- утилиты
const $ = (sel) => document.querySelector(sel);

const fmt = (b) => {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(1)} ${u[i]}`;
};

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = Array.isArray(j.detail) ? j.detail.map((d) => d.msg).join("; ") : (j.detail ?? msg);
    } catch (_) { /* не JSON */ }
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}

// ---------------------------------------------------------------- System
async function loadSystem() {
  const s = await api("GET", "/api/system/resource");
  $("#sysinfo").innerHTML =
    `${esc(s.hostname)}<br>kernel ${esc(s.kernel)}<br>mode: ${esc(s.mode)}<br>ip_forward: ${s.ip_forward ? "on" : "off"}`;
}

// ---------------------------------------------------------------- WAN
const STATE_TEXT = {
  bound: "адрес получен по DHCP",
  searching: "ищу DHCP-сервер…",
  static: "настроен вручную",
  none: "не управляется роутером",
};
let wanFormLoaded = false;

function wanModeChanged() {
  const mode = $("#wan-form").querySelector("input[name=mode]:checked")?.value;
  $("#wan-static").hidden = mode !== "static";
}

function fillWanForm(w) {
  const f = $("#wan-form");
  const c = w.config;
  const opts = ["auto", ...w.interfaces];
  if (c.interface !== "auto" && !opts.includes(c.interface)) opts.push(c.interface);
  $("#wan-iface").innerHTML = opts.map((n) =>
    `<option value="${esc(n)}" ${n === c.interface ? "selected" : ""}>${n === "auto" ? "auto (по маршруту по умолчанию)" : esc(n)}</option>`).join("");
  f.querySelector(`input[name=mode][value=${c.mode}]`).checked = true;
  f.address.value = c.address ?? "";
  f.gateway.value = c.gateway ?? "";
  f.dns1.value = c.dns[0] ?? "";
  f.dns2.value = c.dns[1] ?? "";
  wanModeChanged();
}

async function loadWan() {
  const w = await api("GET", "/api/wan");
  $("#ws-iface").textContent = w.interface ?? "не найден";
  $("#ws-link").innerHTML = w.link_up ? '<span class="flag-r">есть</span>' : '<span class="flag-x">нет кабеля</span>';
  $("#ws-state").textContent = STATE_TEXT[w.dhcp_state] ?? (w.dhcp_state || "—");
  $("#ws-addr").innerHTML = w.addresses.length ? w.addresses.map(esc).join("<br>") : "—";
  $("#ws-gw").textContent = w.gateway ?? "—";
  $("#ws-dns").textContent = w.dns.length ? w.dns.join(", ") : "—";
  $("#ws-mac").textContent = w.mac ?? "—";
  $("#ws-lease").textContent = w.lease_expires ? new Date(w.lease_expires * 1000).toLocaleString() : "—";
  $("#wan-renew").hidden = !w.dhcp_running;
  if (!wanFormLoaded) { fillWanForm(w); wanFormLoaded = true; }
}

$("#wan-form").addEventListener("change", (ev) => { if (ev.target.name === "mode") wanModeChanged(); });

$("#wan-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  const mode = f.get("mode");
  $("#wan-error").textContent = "";
  $("#wan-ok").textContent = "";
  try {
    const w = await api("PUT", "/api/wan", {
      interface: f.get("interface"),
      mode,
      address: mode === "static" ? f.get("address") || null : null,
      gateway: mode === "static" ? f.get("gateway") || null : null,
      dns: [f.get("dns1"), f.get("dns2")].filter(Boolean),
    });
    fillWanForm(w);
    $("#wan-ok").textContent = "Применено";
    await loadWan();
  } catch (e) {
    $("#wan-error").textContent = e.message;
  }
});

$("#wan-renew").addEventListener("click", async () => {
  try { await api("POST", "/api/wan/renew"); await loadWan(); }
  catch (e) { $("#wan-error").textContent = e.message; }
});

// ---------------------------------------------------------------- LAN
const ROLE = { wan: '<span class="badge wan">WAN</span>', lan: '<span class="badge lan">LAN</span>', none: "—" };
let lanFormLoaded = false;

function lanPortsAutoChanged() {
  const auto = $("#lan-form").ports_auto.checked;
  $("#lan-port-list").querySelectorAll("input").forEach((i) => { i.disabled = auto; });
}

function fillLanForm(l) {
  const f = $("#lan-form");
  const c = l.config;
  f.enabled.checked = c.enabled;
  f.address.value = c.address;
  f.ports_auto.checked = c.ports.length === 0;
  const candidates = l.ports.filter((p) => p.role !== "wan");
  $("#lan-port-list").innerHTML = candidates.map((p) => `
    <label class="check"><input type="checkbox" name="port" value="${esc(p.name)}"
      ${c.ports.length === 0 || c.ports.includes(p.name) ? "checked" : ""}> ${esc(p.name)}</label>`).join("")
    || '<span class="hint">нет свободных портов</span>';
  f.dhcp_enabled.checked = c.dhcp_enabled;
  f.pool_start.value = c.pool_start ?? "";
  f.pool_end.value = c.pool_end ?? "";
  f.lease_time.value = c.lease_time;
  if (!f.lease_time.value) f.lease_time.add(new Option(c.lease_time, c.lease_time, true, true));
  f.wan_management.checked = c.wan_management;
  lanPortsAutoChanged();
}

async function loadLan() {
  const l = await api("GET", "/api/lan");
  $("#ls-state").innerHTML = l.active ? '<span class="flag-r">работает</span>'
    : (l.config.enabled ? '<span class="flag-x">ошибка — см. docker logs</span>' : "выключен");
  $("#ls-dns").textContent = l.dns_dhcp_running ? "dnsmasq работает" : "не запущен";
  $("#ls-bridge").textContent = l.active ? l.bridge : "—";
  $("#ls-addr").textContent = l.active ? l.config.address : "—";
  $("#lan-ports").innerHTML = l.ports.map((p) => `
    <tr><td>${esc(p.name)}</td><td>${ROLE[p.role]}</td>
        <td>${p.link_up ? '<span class="flag-r">есть</span>' : '<span class="flag-x">нет</span>'}</td>
        <td>${esc(p.mac)}</td></tr>`).join("");
  $("#lan-leases").innerHTML = l.leases.map((d) => `
    <tr><td>${esc(d.hostname ?? "—")}</td><td>${esc(d.ip)}</td><td>${esc(d.mac)}</td>
        <td>${esc(d.vendor ?? "—")}</td>
        <td>${d.expires ? new Date(d.expires * 1000).toLocaleString() : "бессрочно"}</td></tr>`).join("")
    || '<tr><td colspan="5" class="hint">пока никого</td></tr>';
  if (!lanFormLoaded) { fillLanForm(l); lanFormLoaded = true; }
}

$("#lan-form").addEventListener("change", (ev) => { if (ev.target.name === "ports_auto") lanPortsAutoChanged(); });

$("#lan-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  $("#lan-error").textContent = "";
  $("#lan-ok").textContent = "";
  const ports = f.ports_auto.checked ? []
    : [...f.querySelectorAll("input[name=port]:checked")].map((i) => i.value);
  try {
    const l = await api("PUT", "/api/lan", {
      enabled: f.enabled.checked,
      address: f.address.value,
      ports,
      dhcp_enabled: f.dhcp_enabled.checked,
      pool_start: f.pool_start.value || null,
      pool_end: f.pool_end.value || null,
      lease_time: f.lease_time.value,
      wan_management: f.wan_management.checked,
    });
    fillLanForm(l);
    $("#lan-ok").textContent = "Применено";
    await loadLan();
  } catch (e) {
    $("#lan-error").textContent = e.message;
  }
});

// ---------------------------------------------------------------- Interfaces
let interfacesCache = [];

async function loadInterfaces() {
  interfacesCache = await api("GET", "/api/interfaces");
  $("#ifaces").innerHTML = interfacesCache.map((i) => `
    <tr>
      <td>${i.running ? '<span class="flag-r">R</span>' : '<span class="flag-x">X</span>'}</td>
      <td>${esc(i.name)}</td>
      <td>${esc(i.mac)}</td>
      <td>${i.mtu ?? ""}</td>
      <td>${i.addresses.map(esc).join("<br>")}</td>
      <td>${fmt(i.rx_bytes)}</td>
      <td>${fmt(i.tx_bytes)}</td>
    </tr>`).join("");
}

// ---------------------------------------------------------------- IP → Addresses
async function loadAddresses() {
  if (!interfacesCache.length) await loadInterfaces();
  const sel = $("#addr-iface");
  const current = sel.value;
  sel.innerHTML = interfacesCache
    .filter((i) => i.name !== "lo")
    .map((i) => `<option ${i.name === current ? "selected" : ""}>${esc(i.name)}</option>`).join("");

  const list = await api("GET", "/api/ip/addresses");
  $("#addrs").innerHTML = list.map((a, n) => {
    const flags = (a.disabled ? "X" : "") + (a.invalid ? "I" : "") + (a.dynamic ? "D" : "");
    const actions = a.dynamic ? "" : `
        <button data-act="toggle" data-id="${a.id}" data-disabled="${a.disabled}">
          ${a.disabled ? "Enable" : "Disable"}</button>
        <button data-act="remove" data-id="${a.id}" class="danger">Remove</button>`;
    return `
      <tr class="${a.disabled ? "row-disabled" : ""} ${a.dynamic ? "row-dynamic" : ""}">
        <td>${n}</td>
        <td class="flags">${flags}</td>
        <td>${esc(a.address)}</td>
        <td>${esc(a.network)}</td>
        <td>${esc(a.interface)}</td>
        <td>${esc(a.comment)}</td>
        <td class="actions">${actions}</td>
      </tr>`;
  }).join("");
}

$("#addr-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  $("#addr-error").textContent = "";
  try {
    await api("POST", "/api/ip/addresses", {
      address: f.get("address"),
      interface: f.get("interface"),
      comment: f.get("comment") || null,
    });
    ev.target.address.value = "";
    ev.target.comment.value = "";
    await loadInterfaces();
    await loadAddresses();
  } catch (e) {
    $("#addr-error").textContent = e.message;
  }
});

$("#addrs").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  $("#addr-error").textContent = "";
  try {
    if (btn.dataset.act === "toggle") {
      await api("PATCH", `/api/ip/addresses/${id}`, { disabled: btn.dataset.disabled !== "true" });
    } else if (btn.dataset.act === "remove") {
      await api("DELETE", `/api/ip/addresses/${id}`);
    }
    await loadInterfaces();
    await loadAddresses();
  } catch (e) {
    $("#addr-error").textContent = e.message;
  }
});

// ---------------------------------------------------------------- IP → Routes
async function loadRoutes() {
  const list = await api("GET", "/api/ip/routes");
  $("#routes").innerHTML = list.map((r, n) => {
    const flags = (r.disabled ? "X" : "") + (r.dynamic ? "D" : "") + (r.active ? "A" : "")
                + (r.connected ? "C" : "") + (r.static ? "S" : "");
    const actions = r.dynamic ? "" : `
        <button data-act="toggle" data-id="${r.id}" data-disabled="${r.disabled}">
          ${r.disabled ? "Enable" : "Disable"}</button>
        <button data-act="remove" data-id="${r.id}" class="danger">Remove</button>`;
    const cls = [r.disabled && "row-disabled", r.dynamic && "row-dynamic",
                 r.static && !r.active && !r.disabled && "row-inactive"].filter(Boolean).join(" ");
    return `
      <tr class="${cls}">
        <td>${n}</td>
        <td class="flags">${flags}</td>
        <td>${esc(r.dst_address)}</td>
        <td>${esc(r.gateway)}</td>
        <td>${r.distance}</td>
        <td>${esc(r.interface)}</td>
        <td>${esc(r.comment)}</td>
        <td class="actions">${actions}</td>
      </tr>`;
  }).join("");
}

$("#route-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = new FormData(ev.target);
  $("#route-error").textContent = "";
  try {
    await api("POST", "/api/ip/routes", {
      dst_address: f.get("dst_address") || "0.0.0.0/0",
      gateway: f.get("gateway"),
      distance: Number(f.get("distance") || 1),
      comment: f.get("comment") || null,
    });
    ev.target.reset();
    await loadRoutes();
  } catch (e) {
    $("#route-error").textContent = e.message;
  }
});

$("#routes").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  $("#route-error").textContent = "";
  try {
    if (btn.dataset.act === "toggle") {
      await api("PATCH", `/api/ip/routes/${id}`, { disabled: btn.dataset.disabled !== "true" });
    } else if (btn.dataset.act === "remove") {
      await api("DELETE", `/api/ip/routes/${id}`);
    }
    await loadRoutes();
  } catch (e) {
    $("#route-error").textContent = e.message;
  }
});

// ---------------------------------------------------------------- навигация
const pages = {
  "wan": loadWan,
  "lan": loadLan,
  "interfaces": loadInterfaces,
  "ip-addresses": loadAddresses,
  "ip-routes": loadRoutes,
};
let timer = null;

function show() {
  const page = pages[location.hash.slice(1)] ? location.hash.slice(1) : "wan";
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${page}`));
  document.querySelectorAll("nav a[data-page]").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  clearInterval(timer);
  const load = () => pages[page]().catch((e) => console.error(e));
  load();
  timer = setInterval(load, page === "ip-addresses" || page === "ip-routes" ? 5000 : 3000);
}

window.addEventListener("hashchange", show);
loadSystem().catch(console.error);
show();
