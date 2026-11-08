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
    <tr><td>${esc(d.name ?? d.hostname ?? "—")}</td><td>${esc(d.ip)}</td><td>${esc(d.mac)}</td>
        <td>${esc(d.vendor ?? "—")}</td>
        <td>${d.expires ? new Date(d.expires * 1000).toLocaleString() : "бессрочно"}</td>
        <td class="actions">${d.static ? '<span class="badge lan">закреплён</span>'
          : `<button type="button" data-pin="${esc(d.mac)}" data-ip="${esc(d.ip)}" data-name="${esc(d.hostname ?? "")}">Закрепить</button>`}</td></tr>`).join("")
    || '<tr><td colspan="6" class="hint">пока никого</td></tr>';
  renderStatic(l.static_leases);
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

// ---------------------------------------------------------------- LAN: закреплённые адреса
function renderStatic(list) {
  $("#static-leases").innerHTML = list.map((x) => `
    <tr class="${x.valid ? "" : "row-inactive"}"><td>${esc(x.name ?? "—")}</td><td>${esc(x.ip)}</td><td>${esc(x.mac)}</td>
      <td>${!x.valid ? "вне сети LAN — не работает" : x.in_pool ? "внутри пула DHCP" : ""}</td>
      <td class="actions"><button type="button" data-unpin="${esc(x.mac)}" class="danger">Открепить</button></td></tr>`).join("")
    || '<tr><td colspan="5" class="hint">нет</td></tr>';
}

$("#lan-leases").addEventListener("click", (ev) => {
  const b = ev.target.closest("button[data-pin]");
  if (!b) return;
  const f = $("#static-form");
  f.mac.value = b.dataset.pin;
  f.ip.value = b.dataset.ip;
  f.name.value = b.dataset.name;
  $("#static-card").scrollIntoView({ behavior: "smooth" });
  f.ip.focus();
});

$("#static-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  $("#static-error").textContent = "";
  try {
    renderStatic(await api("POST", "/api/lan/static-leases",
      { mac: f.mac.value, ip: f.ip.value, name: f.name.value || null }));
    f.reset();
    await loadLan();
  } catch (e) { $("#static-error").textContent = e.message; }
});

$("#static-leases").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button[data-unpin]");
  if (!b) return;
  $("#static-error").textContent = "";
  try {
    renderStatic(await api("DELETE", `/api/lan/static-leases/${encodeURIComponent(b.dataset.unpin)}`));
    await loadLan();
  } catch (e) { $("#static-error").textContent = e.message; }
});

// ---------------------------------------------------------------- VPN: вкладки
let vpnKind = "wireguard";
let wgFormLoaded = false;
let l2tpFormLoaded = false;
const VPN_NAMES = { wireguard: "WireGuard", amneziawg: "AmneziaWG", l2tp: "L2TP/IPsec" };
const splitList = (v) => v.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);

function selectVpnTab(kind) {
  vpnKind = kind;
  wgFormLoaded = false;
  l2tpFormLoaded = false;
  document.querySelectorAll("#vpn-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.kind === kind));
  $("#wg-panel").hidden = kind === "l2tp";
  $("#l2tp-panel").hidden = kind !== "l2tp";
  $("#awg-obf").hidden = kind !== "amneziawg";
  ["#wg-error", "#wg-ok", "#wg-parse-msg", "#l2tp-error", "#l2tp-ok"].forEach((id) => { $(id).textContent = ""; });
  loadVpn().catch(console.error);
}

$("#vpn-tabs").addEventListener("click", (ev) => {
  const t = ev.target.closest(".tab");
  if (t) selectVpnTab(t.dataset.kind);
});

async function loadVpn() {
  const sum = await api("GET", "/api/vpn");
  document.querySelectorAll("#vpn-tabs .tab").forEach((t) => {
    t.textContent = VPN_NAMES[t.dataset.kind] + (sum.enabled === t.dataset.kind ? " ●" : "");
  });
  $("#vpn-active-hint").textContent = sum.enabled
    ? `Сейчас включён: ${VPN_NAMES[sum.enabled]}. Одновременно работает один туннель — включение другого выключит этот.`
    : "Туннель не включён. Одновременно работает один туннель.";
  return vpnKind === "l2tp" ? loadL2tp() : loadWg();
}

function ago(ts) {
  const s = Math.round(Date.now() / 1000 - ts);
  return s < 60 ? `${s} с назад` : s < 3600 ? `${Math.round(s / 60)} мин назад` : new Date(ts * 1000).toLocaleString();
}

// ---------------------------------------------------------------- VPN → WireGuard / AmneziaWG
function wgModeChanged() {
  const f = $("#wg-form");
  f.killswitch.disabled = f.querySelector("input[name=mode]:checked")?.value !== "full";
}

function fillWgForm(c, privateKeySet) {
  const f = $("#wg-form");
  f.enabled.checked = c.enabled;
  f.querySelector(`input[name=mode][value=${c.mode}]`).checked = true;
  f.killswitch.checked = c.killswitch;
  f.nat.checked = c.nat;
  f.private_key.value = c.private_key ?? "";
  f.private_key.placeholder = privateKeySet ? "задан — пусто = не менять" : "";
  f.addresses.value = c.addresses.join(", ");
  f.dns.value = c.dns.join(", ");
  f.mtu.value = c.mtu;
  f.peer_public_key.value = c.peer_public_key ?? "";
  f.preshared_key.value = c.preshared_key ?? "";
  f.endpoint.value = c.endpoint ?? "";
  f.allowed_ips.value = c.allowed_ips.join(", ");
  f.keepalive.value = c.keepalive;
  f.obfuscation.value = Object.entries(c.obfuscation ?? {}).map(([k, v]) => `${k} = ${v}`).join("\n");
  wgModeChanged();
}

function parseObfuscation(text) {
  const out = {};
  text.split("\n").map((l) => l.trim()).filter(Boolean).forEach((l) => {
    const i = l.indexOf("=");
    if (i > 0) out[l.slice(0, i).trim()] = l.slice(i + 1).trim();
  });
  return out;
}

async function loadWg() {
  const w = await api("GET", `/api/vpn/${vpnKind}`);
  $("#vs-state").innerHTML = !w.config.enabled ? "выключен"
    : w.connected ? '<span class="flag-r">подключён</span>'
    : w.active ? '<span class="flag-x">нет связи с сервером</span>' : '<span class="flag-x">ошибка — см. docker logs</span>';
  $("#vs-hs").textContent = w.latest_handshake ? ago(w.latest_handshake) : "—";
  $("#vs-endpoint").textContent = w.config.endpoint ? `${w.config.endpoint}${w.endpoint_ip ? " (" + w.endpoint_ip + ")" : ""}` : "—";
  $("#vs-traffic").textContent = w.active ? `↓ ${fmt(w.rx_bytes)}  ↑ ${fmt(w.tx_bytes)}` : "—";
  $("#vs-pub").textContent = w.public_key ?? "—";
  $("#vs-error").textContent = w.error ?? "";
  if (!wgFormLoaded) { fillWgForm(w.config, w.private_key_set); wgFormLoaded = true; }
}

$("#wg-form").addEventListener("change", (ev) => { if (ev.target.name === "mode") wgModeChanged(); });

$("#wg-file").addEventListener("change", async (ev) => {
  const file = ev.target.files[0];
  if (file) $("#wg-import").value = await file.text();
});

$("#wg-parse").addEventListener("click", async () => {
  $("#wg-parse-msg").textContent = "";
  $("#wg-error").textContent = "";
  try {
    const c = await api("POST", `/api/vpn/${vpnKind}/parse`, { text: $("#wg-import").value });
    c.enabled = true;
    fillWgForm(c, false);
    $("#wg-parse-msg").textContent = "Поля заполнены — проверьте и нажмите «Применить»";
  } catch (e) { $("#wg-error").textContent = e.message; }
});

$("#wg-genkey").addEventListener("click", async () => {
  try {
    const k = await api("POST", "/api/vpn/genkey");
    $("#wg-form").private_key.value = k.private_key;
    $("#wg-ok").textContent = `Публичный ключ роутера: ${k.public_key}`;
  } catch (e) { $("#wg-error").textContent = e.message; }
});

$("#wg-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  $("#wg-error").textContent = "";
  $("#wg-ok").textContent = "";
  try {
    const w = await api("PUT", `/api/vpn/${vpnKind}`, {
      enabled: f.enabled.checked,
      mode: f.querySelector("input[name=mode]:checked").value,
      killswitch: f.killswitch.checked,
      nat: f.nat.checked,
      private_key: f.private_key.value || null,
      addresses: splitList(f.addresses.value),
      dns: splitList(f.dns.value),
      mtu: Number(f.mtu.value || 1420),
      peer_public_key: f.peer_public_key.value || null,
      preshared_key: f.preshared_key.value || null,
      endpoint: f.endpoint.value || null,
      allowed_ips: splitList(f.allowed_ips.value),
      keepalive: Number(f.keepalive.value || 0),
      obfuscation: vpnKind === "amneziawg" ? parseObfuscation(f.obfuscation.value) : {},
    });
    fillWgForm(w.config, w.private_key_set);
    $("#wg-ok").textContent = "Применено";
    await loadVpn();
  } catch (e) { $("#wg-error").textContent = e.message; }
});

// ---------------------------------------------------------------- VPN → L2TP/IPsec
function l2tpModeChanged() {
  const f = $("#l2tp-form");
  f.killswitch.disabled = f.querySelector("input[name=mode]:checked")?.value !== "full";
}

function fillL2tpForm(st) {
  const f = $("#l2tp-form");
  const c = st.config;
  f.enabled.checked = c.enabled;
  f.querySelector(`input[name=mode][value=${c.mode}]`).checked = true;
  f.killswitch.checked = c.killswitch;
  f.nat.checked = c.nat;
  f.server.value = c.server ?? "";
  f.psk.value = "";
  f.psk.placeholder = st.psk_set ? "задан — пусто = не менять" : "";
  f.username.value = c.username ?? "";
  f.password.value = "";
  f.password.placeholder = st.password_set ? "задан — пусто = не менять" : "";
  f.networks.value = c.networks.join(", ");
  f.mtu.value = c.mtu;
  l2tpModeChanged();
}

async function loadL2tp() {
  const st = await api("GET", "/api/vpn/l2tp");
  $("#ls2-state").innerHTML = !st.config.enabled ? "выключен"
    : st.connected ? '<span class="flag-r">подключён</span>' : '<span class="flag-x">подключаюсь…</span>';
  $("#ls2-ipsec").innerHTML = !st.config.enabled ? "—"
    : st.ipsec_up ? '<span class="flag-r">установлен</span>' : '<span class="flag-x">нет</span>';
  $("#ls2-server").textContent = st.config.server ? `${st.config.server}${st.endpoint_ip ? " (" + st.endpoint_ip + ")" : ""}` : "—";
  $("#ls2-ip").textContent = st.local_ip ? `${st.local_ip} ↔ ${st.remote_ip}` : "—";
  $("#ls2-traffic").textContent = st.connected ? `↓ ${fmt(st.rx_bytes)}  ↑ ${fmt(st.tx_bytes)}` : "—";
  $("#ls2-error").textContent = st.error ?? "";
  if (!l2tpFormLoaded) { fillL2tpForm(st); l2tpFormLoaded = true; }
}

$("#l2tp-form").addEventListener("change", (ev) => { if (ev.target.name === "mode") l2tpModeChanged(); });

$("#l2tp-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  $("#l2tp-error").textContent = "";
  $("#l2tp-ok").textContent = "";
  try {
    const st = await api("PUT", "/api/vpn/l2tp", {
      enabled: f.enabled.checked,
      mode: f.querySelector("input[name=mode]:checked").value,
      killswitch: f.killswitch.checked,
      nat: f.nat.checked,
      server: f.server.value || null,
      psk: f.psk.value || null,
      username: f.username.value || null,
      password: f.password.value || null,
      networks: splitList(f.networks.value),
      mtu: Number(f.mtu.value || 1400),
    });
    fillL2tpForm(st);
    $("#l2tp-ok").textContent = "Применено";
    await loadVpn();
  } catch (e) { $("#l2tp-error").textContent = e.message; }
});

// ---------------------------------------------------------------- Firewall
let fwTab = "input";
let fwEditId = null;     // id правила, которое редактируем (null — новое)
let pfEditId = null;
let fwData = null;
const ZONE = { any: "Любой", wan: "WAN", lan: "LAN", vpn: "VPN" };
const ACTION = { accept: '<span class="act accept">Разрешить</span>', drop: '<span class="act drop">Запретить</span>',
                 reject: '<span class="act drop">Отклонить</span>' };
const PROTO = { all: "Все", tcp: "TCP", udp: "UDP", icmp: "ICMP", "tcp+udp": "TCP и UDP" };
const HINTS = {
  input: "Кто может подключаться к самому роутеру. Правила проверяются сверху вниз, первое совпавшее решает; затем — системные правила.",
  forward: "Трафик через роутер между LAN, WAN и VPN. Например: запретить устройству интернет или открыть центру по VPN только нужный порт.",
};

function selectFwTab(tab) {
  fwTab = tab;
  document.querySelectorAll("#fw-tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
  $("#fw-rules-panel").hidden = !(tab === "input" || tab === "forward");
  $("#fw-forwards-panel").hidden = tab !== "forwards";
  $("#fw-ruleset-panel").hidden = tab !== "ruleset";
  document.querySelectorAll(".fwd-col").forEach((c) => { c.hidden = tab !== "forward"; });
  closeFwForm();
  loadFirewall().catch(console.error);
}

$("#fw-tabs").addEventListener("click", (ev) => {
  const t = ev.target.closest(".tab");
  if (t) selectFwTab(t.dataset.tab);
});

const counter = (x) => x.packets ? `${x.packets} пак. / ${fmt(x.bytes)}` : "—";
const cidr = (v) => v ?? '<span class="hint">0.0.0.0/0</span>';

async function loadFirewall() {
  if (fwTab === "ruleset") {
    $("#fw-ruleset").textContent = (await api("GET", "/api/firewall/ruleset")).text;
    return;
  }
  fwData = await api("GET", "/api/firewall");
  const z = fwData.zones;
  $("#fw-zones").innerHTML = (fwData.active ? '<span class="badge lan">фаервол активен</span>'
      : '<span class="badge wan">не активен — включите LAN</span>')
    + ` WAN: <b>${esc(z.wan ?? "—")}</b> · LAN: <b>${esc(z.lan ?? "—")}</b> · VPN: <b>${esc(z.vpn ?? "—")}</b>`;

  if (fwTab === "forwards") {
    $("#pf-list").innerHTML = fwData.forwards.map((f) => `
      <tr class="${f.enabled ? "" : "row-disabled"}"><td>${f.id}</td><td>${PROTO[f.protocol]}</td><td>${esc(f.wan_port)}</td>
        <td>${esc(f.to_ip)}</td><td>${f.to_port ?? esc(f.wan_port)}</td><td>${cidr(f.src)}</td>
        <td class="desc">${esc(f.description ?? "")}</td><td>${counter(f)}</td>
        <td class="actions"><button type="button" data-pf-edit="${f.id}">Изменить</button>
          <button type="button" data-pf-del="${f.id}" class="danger">Удалить</button></td></tr>`).join("")
      || '<tr><td colspan="9" class="hint">пробросов нет</td></tr>';
    return;
  }

  $("#fw-rules-hint").textContent = HINTS[fwTab];
  const rules = fwData.rules.filter((r) => r.chain === fwTab);
  const fwd = fwTab === "forward";
  $("#fw-rules").innerHTML = rules.map((r, i) => `
    <tr class="${r.enabled ? "" : "row-disabled"}">
      <td>${i + 1}</td><td>${ACTION[r.action]}</td><td>${ZONE[r.in_zone]}</td><td>${cidr(r.src)}</td>
      ${fwd ? `<td>${ZONE[r.out_zone]}</td><td>${cidr(r.dst)}</td>` : ""}
      <td>${PROTO[r.protocol]}</td><td>${esc(r.src_ports ?? "Все")}</td><td>${esc(r.dst_ports ?? "Все")}</td>
      <td class="desc">${esc(r.description ?? "")}</td><td>${counter(r)}</td>
      <td class="actions">
        <button type="button" data-move="up" data-id="${r.id}" ${i === 0 ? "disabled" : ""}>↑</button>
        <button type="button" data-move="down" data-id="${r.id}" ${i === rules.length - 1 ? "disabled" : ""}>↓</button>
        <button type="button" data-edit="${r.id}">Изменить</button>
        <button type="button" data-del="${r.id}" class="danger">Удалить</button></td>
    </tr>`).join("") || `<tr><td colspan="${fwd ? 12 : 10}" class="hint">своих правил нет — работают только системные</td></tr>`;
  $("#fw-system").innerHTML = fwData.system[fwTab].map((x) => `<li>${esc(x)}</li>`).join("")
    + (fwd ? "" : fwData.system.nat.map((x) => `<li>NAT: ${esc(x)}</li>`).join(""));
}

// --- форма правила ---
function openFwForm(rule) {
  const f = $("#fw-form");
  fwEditId = rule ? rule.id : null;
  $("#fw-form-title").textContent = rule ? `Правило #${rules_index(rule)} — изменить` : (fwTab === "input"
    ? "Новое правило: входящие на роутер" : "Новое правило: транзит");
  $("#fw-save").textContent = rule ? "Сохранить" : "Добавить";
  const r = rule ?? { action: "accept", protocol: "tcp", in_zone: fwTab === "input" ? "wan" : "lan",
                      out_zone: "any", enabled: true };
  f.action.value = r.action; f.protocol.value = r.protocol;
  f.in_zone.value = r.in_zone; f.out_zone.value = r.out_zone;
  f.src.value = r.src ?? ""; f.dst.value = r.dst ?? "";
  f.src_ports.value = r.src_ports ?? ""; f.dst_ports.value = r.dst_ports ?? "";
  f.description.value = r.description ?? ""; f.enabled.checked = r.enabled;
  f.querySelectorAll(".fwd-only").forEach((el) => { el.hidden = fwTab !== "forward"; });
  fwProtoChanged();
  f.hidden = false;
  $("#fw-error").textContent = "";
}
const rules_index = (rule) => fwData.rules.filter((r) => r.chain === rule.chain).findIndex((r) => r.id === rule.id) + 1;

function closeFwForm() { $("#fw-form").hidden = true; $("#pf-form").hidden = true; fwEditId = pfEditId = null; }

function fwProtoChanged() {
  const f = $("#fw-form");
  const ports = f.protocol.value === "tcp" || f.protocol.value === "udp";
  f.querySelectorAll(".ports input").forEach((i) => { i.disabled = !ports; if (!ports) i.value = ""; });
}

$("#fw-add").addEventListener("click", () => openFwForm(null));
$("#fw-cancel").addEventListener("click", closeFwForm);
$("#fw-form").addEventListener("change", (ev) => { if (ev.target.name === "protocol") fwProtoChanged(); });

$("#fw-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const body = {
    chain: fwTab, action: f.action.value, protocol: f.protocol.value,
    in_zone: f.in_zone.value, out_zone: fwTab === "forward" ? f.out_zone.value : "any",
    src: f.src.value || null, dst: fwTab === "forward" ? f.dst.value || null : null,
    src_ports: f.src_ports.value || null, dst_ports: f.dst_ports.value || null,
    description: f.description.value || null, enabled: f.enabled.checked,
  };
  try {
    await api(fwEditId ? "PUT" : "POST", fwEditId ? `/api/firewall/rules/${fwEditId}` : "/api/firewall/rules", body);
    closeFwForm();
    await loadFirewall();
  } catch (e) { $("#fw-error").textContent = e.message; }
});

$("#fw-rules").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  $("#fw-error").textContent = "";
  try {
    if (b.dataset.edit) openFwForm(fwData.rules.find((r) => r.id === Number(b.dataset.edit)));
    else if (b.dataset.del) { await api("DELETE", `/api/firewall/rules/${b.dataset.del}`); await loadFirewall(); }
    else if (b.dataset.move) {
      await api("POST", `/api/firewall/rules/${b.dataset.id}/move`, { direction: b.dataset.move });
      await loadFirewall();
    }
  } catch (e) { $("#fw-error").textContent = e.message; }
});

// --- форма проброса ---
function openPfForm(fwd) {
  const f = $("#pf-form");
  pfEditId = fwd ? fwd.id : null;
  $("#pf-form-title").textContent = fwd ? `Проброс #${fwd.id} — изменить` : "Новый проброс";
  $("#pf-save").textContent = fwd ? "Сохранить" : "Добавить";
  const x = fwd ?? { protocol: "tcp", enabled: true };
  f.protocol.value = x.protocol; f.wan_port.value = x.wan_port ?? ""; f.to_ip.value = x.to_ip ?? "";
  f.to_port.value = x.to_port ?? ""; f.src.value = x.src ?? ""; f.description.value = x.description ?? "";
  f.enabled.checked = x.enabled;
  f.hidden = false;
  $("#pf-error").textContent = "";
}

$("#pf-add").addEventListener("click", () => openPfForm(null));
$("#pf-cancel").addEventListener("click", closeFwForm);

$("#pf-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const body = {
    protocol: f.protocol.value, wan_port: f.wan_port.value, to_ip: f.to_ip.value,
    to_port: f.to_port.value ? Number(f.to_port.value) : null, src: f.src.value || null,
    description: f.description.value || null, enabled: f.enabled.checked,
  };
  try {
    await api(pfEditId ? "PUT" : "POST", pfEditId ? `/api/firewall/forwards/${pfEditId}` : "/api/firewall/forwards", body);
    closeFwForm();
    await loadFirewall();
  } catch (e) { $("#pf-error").textContent = e.message; }
});

$("#pf-list").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  $("#pf-error").textContent = "";
  try {
    if (b.dataset.pfEdit) openPfForm(fwData.forwards.find((x) => x.id === Number(b.dataset.pfEdit)));
    else if (b.dataset.pfDel) { await api("DELETE", `/api/firewall/forwards/${b.dataset.pfDel}`); await loadFirewall(); }
  } catch (e) { $("#pf-error").textContent = e.message; }
});

// ---------------------------------------------------------------- Tools
const ms = (v) => v == null ? "—" : `${v} мс`;
const statusCell = (s) => s === "ok" || s === "open" ? `<span class="flag-r">${s === "ok" ? "ответ" : "открыт"}</span>`
  : `<span class="flag-x">${esc(s === "timeout" ? "нет ответа" : s === "closed" ? "закрыт" : s)}</span>`;

const TOOLS = {
  ping: {
    fields: ["host", "count", "size", "interface"],
    hint: "ICMP echo. Если узел не отвечает на ping — это не всегда значит, что он недоступен: попробуйте TCP Ping.",
    cols: ["#", "От", "TTL", "Время", "Статус"],
    row: (r) => [r.seq, esc(r.from ?? "—"), r.ttl ?? "—", ms(r.time_ms), statusCell(r.status)],
    summary: (d) => `Отправлено ${d.sent ?? "—"}, получено ${d.received ?? "—"}, потери ${d.loss ?? "—"}%`
      + (d.avg != null ? ` · мин/сред/макс ${d.min}/${d.avg}/${d.max} мс` : ""),
  },
  tcp_ping: {
    fields: ["host", "port", "count"],
    hint: "Время установления TCP-соединения. Работает там, где ICMP закрыт: проверка веб-сервера, SIP по TCP, SSH.",
    cols: ["#", "Порт", "Время", "Статус"],
    row: (r) => [r.seq, r.port, ms(r.time_ms), statusCell(r.status)],
    summary: (d) => `Попыток ${d.sent}, открыто ${d.received}, потери ${d.loss}%`
      + (d.avg != null ? ` · мин/сред/макс ${d.min}/${d.avg}/${d.max} мс` : ""),
  },
  traceroute: {
    fields: ["host", "method", "port", "max_hops", "interface"],
    hint: "Путь пакета до узла. «*» — узел не ответил (часто это просто фильтр, а не обрыв). Через VPN видны хопы внутри туннеля.",
    cols: ["Хоп", "Адрес", "Время 1", "Время 2", "Время 3", "Примечание"],
    row: (r) => [r.hop, esc(r.ip ?? "*") + (r.other_ips.length ? `<br><span class="hint">${r.other_ips.map(esc).join(", ")}</span>` : ""),
      ...[0, 1, 2].map((i) => r.times[i] == null ? "*" : `${r.times[i]} мс`), esc(r.notes.join(" "))],
  },
  dns: {
    fields: ["host"],
    hint: "Разрешение имени через DNS роутера — так же, как его видят устройства LAN (через туннель, если VPN «весь трафик»).",
    cols: ["Имя", "Адреса", "Время"],
  },
  neighbors: {
    fields: [],
    hint: "Таблица соседей ядра (ARP): кто в последнее время общался с роутером. Имена — из DHCP и закреплённых адресов.",
    cols: ["IP", "MAC", "Производитель", "Имя", "Интерфейс", "Состояние"],
    row: (r) => [esc(r.ip), esc(r.mac ?? "—"), esc(r.vendor ?? "—"), esc(r.name ?? "—"), esc(r.interface), esc(r.state ?? "")],
  },
  scan: {
    fields: ["network", "ports"],
    hint: "Ping-обход подсети + ARP: находит и устройства, которые не отвечают на ping (телефоны, Windows). Порты проверяются только у найденных.",
    cols: ["IP", "MAC", "Производитель", "Имя", "Ping", "Открытые порты", "Найден по"],
    row: (r) => [esc(r.ip), esc(r.mac ?? "—"), esc(r.vendor ?? "—"), esc(r.name ?? "—"), ms(r.ping_ms),
      r.open_ports ? (r.open_ports.join(", ") || "—") : "", r.source === "arp" ? "ARP" : "ping"],
    summary: (d) => `Сеть ${d.network}: проверено ${d.scanned}, найдено ${d.found}`,
  },
  capture: {
    fields: ["interface", "count", "seconds", "filter"],
    hint: "tcpdump: пакеты в реальном времени, а полный захват — файлом .pcap для Wireshark. Фильтр — выражение BPF.",
    cols: ["Время", "Интерфейс", "Протокол", "Источник", "Назначение", "Инфо"],
    row: (r) => [esc(r.time), esc(r.interface ? `${r.interface} ${r.direction ?? ""}` : "—"), esc(r.proto),
      esc(r.src ?? ""), esc(r.dst ?? ""), `<span class="mono">${esc(r.info)}</span>`],
    summary: (d) => `Захвачено пакетов: ${d.packets}`,
  },
};

let tool = "ping";
let toolWs = null;
let toolInterfaces = null;

function toolBusy(busy) {
  $("#tool-start").disabled = busy;
  $("#tool-stop").disabled = !busy;
  $("#tool-status").textContent = busy ? "выполняется…" : "";
}

async function selectTool(name) {
  if (toolWs) toolWs.close();
  tool = name;
  const t = TOOLS[name];
  document.querySelectorAll("#tool-tabs .tab").forEach((x) => x.classList.toggle("active", x.dataset.tool === name));
  document.querySelectorAll("#tool-form [data-f]").forEach((l) => { l.hidden = !t.fields.includes(l.dataset.f); });
  $("#tool-form").count.max = name === "capture" ? 2000 : 100;
  $("#tool-form").count.value = name === "capture" ? 200 : 4;
  $("#tool-hint").textContent = t.hint;
  $("#tool-head").innerHTML = `<tr>${t.cols.map((c) => `<th>${c}</th>`).join("")}</tr>`;
  $("#tool-rows").innerHTML = "";
  $("#tool-summary").hidden = true;
  $("#tool-error").textContent = "";
  $("#tool-pcap").hidden = true;
  $("#tool-start").textContent = name === "neighbors" ? "Обновить" : "Старт";
  toolBusy(false);
  if (!toolInterfaces) {
    try {
      toolInterfaces = await api("GET", "/api/tools/interfaces");
      const sel = $("#tool-form").interface;
      sel.innerHTML = '<option value="auto">авто</option>'
        + toolInterfaces.interfaces.map((i) => `<option>${esc(i)}</option>`).join("");
      $("#tool-form").network.value = toolInterfaces.scan_network ?? "";
    } catch (e) { console.error(e); }
  }
  $("#tool-form").interface.value = name === "capture" && toolInterfaces?.interfaces.includes("br-lan") ? "br-lan" : "auto";
  if (name === "neighbors") runTool();
}

function addToolRow(r) {
  const tr = document.createElement("tr");
  tr.innerHTML = TOOLS[tool].row(r).map((c) => `<td>${c}</td>`).join("");
  $("#tool-rows").appendChild(tr);
  if ($("#tool-rows").children.length > 2000) $("#tool-rows").firstChild.remove();
}

let summaryData = {};
function showSummary(d) {
  summaryData = { ...summaryData, ...d };
  const fn = TOOLS[tool].summary;
  if (!fn) return;
  $("#tool-summary").textContent = fn(summaryData);
  $("#tool-summary").hidden = false;
}

async function runTool() {
  const f = $("#tool-form");
  $("#tool-rows").innerHTML = "";
  $("#tool-error").textContent = "";
  $("#tool-summary").hidden = true;
  summaryData = {};

  if (tool === "neighbors") {
    try { (await api("GET", "/api/tools/neighbors")).forEach(addToolRow); }
    catch (e) { $("#tool-error").textContent = e.message; }
    return;
  }
  if (tool === "dns") {
    try {
      const d = await api("GET", `/api/tools/dns?host=${encodeURIComponent(f.host.value)}`);
      $("#tool-rows").innerHTML = `<tr><td>${esc(d.host)}</td><td>${d.error ? `<span class="flag-x">${esc(d.error)}</span>`
        : d.addresses.map(esc).join("<br>")}</td><td>${ms(d.time_ms)}</td></tr>`;
    } catch (e) { $("#tool-error").textContent = e.message; }
    return;
  }

  const params = {};
  TOOLS[tool].fields.forEach((name) => { params[name] = f[name].value; });
  const proto = location.protocol === "https:" ? "wss" : "ws";
  toolWs = new WebSocket(`${proto}://${location.host}/api/tools/ws`);
  toolBusy(true);
  toolWs.onopen = () => toolWs.send(JSON.stringify({ tool, params }));
  toolWs.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (ev.type === "row") addToolRow(ev.row);
    else if (ev.type === "summary") { showSummary(ev.data); if (tool === "capture" && ev.data.pcap) $("#tool-pcap").hidden = false; }
    else if (ev.type === "info") $("#tool-status").textContent = ev.text;
    else if (ev.type === "error") $("#tool-error").textContent = ev.text;
  };
  toolWs.onclose = () => { toolBusy(false); toolWs = null; };
}

$("#tool-tabs").addEventListener("click", (ev) => {
  const t = ev.target.closest(".tab");
  if (t) selectTool(t.dataset.tool);
});
$("#tool-form").addEventListener("submit", (ev) => { ev.preventDefault(); runTool(); });
$("#tool-stop").addEventListener("click", () => {
  if (toolWs && toolWs.readyState === WebSocket.OPEN) toolWs.send(JSON.stringify({ action: "stop" }));
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
  "vpn": loadVpn,
  "firewall": loadFirewall,
  "tools": async () => {},          // инструменты обновляются сами, без опроса
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
selectVpnTab("wireguard");
selectFwTab("input");
selectTool("ping");
loadSystem().catch(console.error);
show();
