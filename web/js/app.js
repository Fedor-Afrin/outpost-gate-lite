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

// ---------------------------------------------------------------- навигация
const pages = {
  "interfaces": loadInterfaces,
  "ip-addresses": loadAddresses,
};
let timer = null;

function show() {
  const page = pages[location.hash.slice(1)] ? location.hash.slice(1) : "interfaces";
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === `page-${page}`));
  document.querySelectorAll("nav a[data-page]").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  clearInterval(timer);
  const load = () => pages[page]().catch((e) => console.error(e));
  load();
  timer = setInterval(load, page === "interfaces" ? 3000 : 5000);
}

window.addEventListener("hashchange", show);
loadSystem().catch(console.error);
show();
