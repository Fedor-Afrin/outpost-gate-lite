const fmt = (b) => {
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
  return `${b.toFixed(1)} ${u[i]}`;
};

async function loadSystem() {
  const r = await fetch("/api/system/resource");
  const s = await r.json();
  document.getElementById("sysinfo").textContent =
    `${s.hostname} · kernel ${s.kernel} · mode: ${s.mode} · ip_forward: ${s.ip_forward ? "on" : "off"}`;
}

async function loadInterfaces() {
  const r = await fetch("/api/interfaces");
  const list = await r.json();
  document.getElementById("ifaces").innerHTML = list.map(i => `
    <tr>
      <td>${i.running ? '<span class="flag-r">R</span>' : '<span class="flag-x">X</span>'}</td>
      <td>${i.name}</td>
      <td>${i.mac ?? ""}</td>
      <td>${i.mtu ?? ""}</td>
      <td>${i.addresses.join("<br>")}</td>
      <td>${fmt(i.rx_bytes)}</td>
      <td>${fmt(i.tx_bytes)}</td>
    </tr>`).join("");
}

loadSystem();
loadInterfaces();
setInterval(loadInterfaces, 3000);
