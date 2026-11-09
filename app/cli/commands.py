"""
Команды CLI в стиле MikroTik RouterOS: дерево меню, разбор строки, вывод таблиц, автодополнение.

  [admin@office] > /ip address print
  [admin@office] > /ip address
  [admin@office] /ip address> add address=192.168.88.1/24 interface=eth1
  [admin@office] /ip address> remove 2
  [admin@office] /ip address> ..
  [admin@office] /ip> /ping 8.8.8.8 count=3

Каждая команда — вызов того же REST API, что и у веб-интерфейса (кроме ping/traceroute,
которые запускаются прямо на роутере). Номера строк, как в RouterOS, берутся из последнего print.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass, field
from typing import Callable

from app.cli.api import ApiError


class CliError(Exception):
    pass


class Quit(Exception):
    pass


@dataclass
class Cmd:
    fn: Callable
    help: str
    params: tuple[str, ...] = ()


@dataclass
class Menu:
    help: str
    children: dict = field(default_factory=dict)


@dataclass
class Ctx:
    api: object
    out: Callable[[str], None] = print
    user: str = "admin"
    role: str = "full"
    confirm: Callable[[str], bool] = lambda q: input(q).strip().lower() in ("y", "yes", "д", "да")
    shell: Callable[[], None] | None = None
    numbers: dict = field(default_factory=dict)     # путь меню -> [id строки 0, id строки 1, ...]


# --- вывод -------------------------------------------------------------------------------------------
def fmt_bytes(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return str(n)


def fmt_uptime(sec) -> str:
    if sec is None:
        return "-"
    sec = int(sec)
    d, h, m, s = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60, sec % 60
    return (f"{d}d" if d else "") + f"{h}h{m}m{s}s"


def table(ctx: Ctx, cols: list[str], rows: list[list], flags: list[str] | None = None,
          legend: str | None = None, numbered: bool = True) -> None:
    """Таблица как в RouterOS: легенда флагов, номер, флаги, колонки ЗАГЛАВНЫМИ."""
    if legend:
        ctx.out(f"Flags: {legend}")
    flags = flags or [""] * len(rows)
    fw = max([len(f) for f in flags] + [0])
    cells = [[str(c) if c not in (None, "") else "" for c in r] for r in rows]
    widths = [max([len(h)] + [len(r[i]) for r in cells]) for i, h in enumerate(cols)]
    nw = len(str(max(len(rows) - 1, 0))) if numbered else 0

    def line(num, flag, values):
        prefix = (f"{num:>{nw}} " if numbered else "") + (f"{flag:<{fw}} " if fw else "")
        return (prefix + "  ".join(v.ljust(widths[i]) for i, v in enumerate(values))).rstrip()

    ctx.out(line("#" if numbered else "", "", [c.upper() for c in cols]))
    for i, (flag, r) in enumerate(zip(flags, cells)):
        ctx.out(line(i, flag, r))


def kv(ctx: Ctx, pairs: list[tuple[str, object]]) -> None:
    """Вывод «ключ: значение» с выравниванием, как /system resource print."""
    pairs = [(k, v) for k, v in pairs if v is not None]
    w = max((len(k) for k, _ in pairs), default=0)
    for k, v in pairs:
        if isinstance(v, (list, tuple)):
            v = ",".join(map(str, v)) if v else ""
        elif isinstance(v, bool):
            v = "yes" if v else "no"
        ctx.out(f"{k:>{w}}: {v}")


# --- разбор аргументов --------------------------------------------------------------------------------
def split_args(tokens: list[str]) -> tuple[list[str], dict[str, str]]:
    pos, named = [], {}
    for t in tokens:
        if "=" in t and not t.startswith("="):
            k, v = t.split("=", 1)
            named[k] = v
        else:
            pos.append(t)
    return pos, named


def yes(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.lower() in ("yes", "true", "1", "on", "да")


def parse_numbers(ctx: Ctx, menu: str, pos: list[str], named: dict) -> list:
    """'0,2' или numbers=0,2 -> id строк из последнего print этого меню."""
    raw = named.get("numbers") or ",".join(pos)
    if not raw:
        raise CliError("укажите номер(а) строк из print, например: remove 0,2")
    ids = ctx.numbers.get(menu)
    if ids is None:
        raise CliError(f"сначала выполните print в {menu}")
    out = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit() or int(part) >= len(ids):
            raise CliError(f"no such item ({part})")
        out.append(ids[int(part)])
    return out


def require(named: dict, *names: str) -> None:
    missing = [n for n in names if not named.get(n)]
    if missing:
        raise CliError("missing value(s) of argument(s) " + ", ".join(missing))


# --- /interface ---------------------------------------------------------------------------------------
def interface_print(ctx: Ctx, pos, named):
    items = ctx.api.get("/api/interfaces")
    table(ctx, ["name", "mac-address", "mtu", "address", "rx", "tx"],
          [[i["name"], i.get("mac"), i.get("mtu"), ",".join(i.get("addresses", [])),
            fmt_bytes(i.get("rx_bytes")), fmt_bytes(i.get("tx_bytes"))] for i in items],
          flags=["R" if i.get("running") else "X" for i in items], legend="R - running, X - no link")


# --- /ip address ----------------------------------------------------------------------------------------
def address_print(ctx: Ctx, pos, named):
    items = ctx.api.get("/api/ip/addresses")
    ctx.numbers["/ip address"] = [i.get("id") for i in items]
    table(ctx, ["address", "network", "interface", "comment"],
          [[i["address"], i["network"], i["interface"], i.get("comment")] for i in items],
          flags=[("X" if i["disabled"] else "") + ("I" if i["invalid"] else "") + ("D" if i["dynamic"] else "")
                 for i in items],
          legend="X - disabled, I - invalid, D - dynamic")


def address_add(ctx: Ctx, pos, named):
    require(named, "address", "interface")
    ctx.api.post("/api/ip/addresses", {"address": named["address"], "interface": named["interface"],
                                       "comment": named.get("comment"), "disabled": yes(named.get("disabled"))})


def _dynamic_guard(ids):
    if any(i is None for i in ids):
        raise CliError("dynamic item can not be changed (он не из конфигурации)")


def address_remove(ctx: Ctx, pos, named):
    ids = parse_numbers(ctx, "/ip address", pos, named)
    _dynamic_guard(ids)
    for i in ids:
        ctx.api.delete(f"/api/ip/addresses/{i}")


def _toggle(path: str, menu: str, disabled: bool):
    def fn(ctx: Ctx, pos, named):
        ids = parse_numbers(ctx, menu, pos, named)
        _dynamic_guard(ids)
        for i in ids:
            ctx.api.patch(f"{path}/{i}", {"disabled": disabled})
    return fn


# --- /ip route -----------------------------------------------------------------------------------------------
def route_print(ctx: Ctx, pos, named):
    items = ctx.api.get("/api/ip/routes")
    ctx.numbers["/ip route"] = [i.get("id") for i in items]
    table(ctx, ["dst-address", "gateway", "distance", "interface", "comment"],
          [[i["dst_address"], i["gateway"], i["distance"], i.get("interface"), i.get("comment")] for i in items],
          flags=[("X" if i["disabled"] else "") + ("D" if i["dynamic"] else "") + ("A" if i["active"] else "")
                 + ("C" if i["connected"] else "") + ("S" if i["static"] else "") for i in items],
          legend="X - disabled, D - dynamic, A - active, C - connected, S - static")


def route_add(ctx: Ctx, pos, named):
    require(named, "gateway")
    body = {"dst_address": named.get("dst-address", "0.0.0.0/0"), "gateway": named["gateway"],
            "comment": named.get("comment"), "disabled": yes(named.get("disabled"))}
    if named.get("distance"):
        body["distance"] = int(named["distance"])
    ctx.api.post("/api/ip/routes", body)


def route_remove(ctx: Ctx, pos, named):
    ids = parse_numbers(ctx, "/ip route", pos, named)
    _dynamic_guard(ids)
    for i in ids:
        ctx.api.delete(f"/api/ip/routes/{i}")


# --- /ip dhcp-server -------------------------------------------------------------------------------------------
def dhcp_print(ctx: Ctx, pos, named):
    c = ctx.api.get("/api/lan")["config"]
    kv(ctx, [("enabled", c["enabled"] and c["dhcp_enabled"]), ("interface", "br-lan"), ("address", c["address"]),
             ("pool", f'{c["pool_start"]}-{c["pool_end"]}'), ("lease-time", c["lease_time"])])


def lease_print(ctx: Ctx, pos, named):
    lan = ctx.api.get("/api/lan")
    leases = {l["mac"]: l for l in lan["leases"]}
    rows, flags, ids = [], [], []
    for s in lan["static_leases"]:                                    # закреплённые — первыми
        l = leases.pop(s["mac"], {})
        rows.append([s["ip"], s["mac"], s.get("name") or l.get("hostname"), l.get("vendor"),
                     "bound" if l else "waiting"])
        flags.append("S")
        ids.append(("static", s["mac"], s["ip"], s.get("name")))
    for l in leases.values():
        rows.append([l["ip"], l["mac"], l.get("hostname"), l.get("vendor"), "bound"])
        flags.append("D")
        ids.append(("dynamic", l["mac"], l["ip"], l.get("hostname")))
    ctx.numbers["/ip dhcp-server lease"] = ids
    table(ctx, ["address", "mac-address", "host-name", "vendor", "status"], rows, flags=flags,
          legend="S - static (закреплён), D - dynamic")


def lease_make_static(ctx: Ctx, pos, named):
    for kind, mac, ip, name in parse_numbers(ctx, "/ip dhcp-server lease", pos, named):
        if kind == "static":
            continue
        ctx.api.post("/api/lan/static-leases", {"mac": mac, "ip": ip, "name": name})


def lease_add(ctx: Ctx, pos, named):
    require(named, "mac-address", "address")
    ctx.api.post("/api/lan/static-leases", {"mac": named["mac-address"], "ip": named["address"],
                                            "name": named.get("comment") or named.get("host-name")})


def lease_remove(ctx: Ctx, pos, named):
    for kind, mac, ip, name in parse_numbers(ctx, "/ip dhcp-server lease", pos, named):
        if kind != "static":
            raise CliError(f"{ip}: динамическая аренда — удалить можно только закреплённую")
        ctx.api.delete(f"/api/lan/static-leases/{mac}")


# --- /ip firewall ----------------------------------------------------------------------------------------------
ZONES = {"any": "", "wan": "WAN", "lan": "LAN", "vpn": "VPN"}


def filter_print(ctx: Ctx, pos, named):
    fw = ctx.api.get("/api/firewall")
    rules = fw["rules"]
    table(ctx, ["chain", "action", "in", "out", "src-address", "dst-address", "protocol", "dst-port", "packets",
                "comment"],
          [[r["chain"], r["action"], ZONES[r["in_zone"]], ZONES[r["out_zone"]], r.get("src"), r.get("dst"),
            "" if r["protocol"] == "all" else r["protocol"], r.get("dst_ports"), r["packets"], r.get("description")]
           for r in rules],
          flags=["X" if not r["enabled"] else "" for r in rules], legend="X - disabled")
    ctx.out(";;; системные правила (после ваших):")
    for chain in ("input", "forward"):
        for line in fw["system"][chain]:
            ctx.out(f"    {chain}: {line}")


def nat_print(ctx: Ctx, pos, named):
    fw = ctx.api.get("/api/firewall")
    fwd = fw["forwards"]
    table(ctx, ["chain", "action", "protocol", "dst-port", "to-address", "to-port", "src-address", "packets",
                "comment"],
          [["dstnat", "dst-nat", f["protocol"], f["wan_port"], f["to_ip"], f.get("to_port"), f.get("src"),
            f["packets"], f.get("description")] for f in fwd],
          flags=["X" if not f["enabled"] else "" for f in fwd], legend="X - disabled")
    for line in fw["system"]["nat"]:
        ctx.out(f";;; srcnat: {line}")


# --- /ip dns ---------------------------------------------------------------------------------------------------
def dns_print(ctx: Ctx, pos, named):
    w = ctx.api.get("/api/wan")
    lan = ctx.api.get("/api/lan")
    kv(ctx, [("servers", w["dns"]), ("allow-remote-requests", lan["dns_dhcp_running"]),
             ("listen", lan["config"]["address"].split("/")[0] if lan["active"] else "-")])


# --- /wan, /lan, /vpn ---------------------------------------------------------------------------------------------
def wan_print(ctx: Ctx, pos, named):
    w = ctx.api.get("/api/wan")
    kv(ctx, [("interface", w["interface"]), ("mode", w["config"]["mode"]), ("link", w["link_up"]),
             ("address", w["addresses"]), ("gateway", w["gateway"]), ("dns", w["dns"]),
             ("dhcp-status", w["dhcp_state"]), ("mac-address", w.get("mac"))])


def wan_set(ctx: Ctx, pos, named):
    cfg = ctx.api.get("/api/wan")["config"]
    if "dns" in named:
        cfg["dns"] = [d for d in named.pop("dns").split(",") if d]
    for key in ("interface", "mode", "address", "gateway"):
        if key in named:
            cfg[key] = named[key] or None
    ctx.api.put("/api/wan", cfg)


def wan_renew(ctx: Ctx, pos, named):
    ctx.api.post("/api/wan/renew")


def lan_print(ctx: Ctx, pos, named):
    l = ctx.api.get("/api/lan")
    c = l["config"]
    kv(ctx, [("enabled", c["enabled"]), ("running", l["active"]), ("address", c["address"]),
             ("ports", [f'{p["name"]}{"" if p["link_up"] else "(no-link)"}' for p in l["ports"] if p["role"] == "lan"]),
             ("dhcp-server", c["dhcp_enabled"]), ("pool", f'{c["pool_start"]}-{c["pool_end"]}'),
             ("lease-time", c["lease_time"]), ("wan-management", c["wan_management"]),
             ("clients", len(l["leases"]))])


VPN_NAMES = {"wireguard": "WireGuard", "amneziawg": "AmneziaWG", "l2tp": "L2TP/IPsec"}


def vpn_print(ctx: Ctx, pos, named):
    kind = ctx.api.get("/api/vpn")["enabled"]
    if not kind:
        ctx.out("туннель выключен (включается в веб-интерфейсе: VPN)")
        return
    st = ctx.api.get(f"/api/vpn/{kind}")
    c = st["config"]
    hs = st.get("latest_handshake")
    kv(ctx, [("type", VPN_NAMES[kind]), ("connected", st.get("connected")),
             ("server", c.get("endpoint") or c.get("server")), ("server-ip", st.get("endpoint_ip")),
             ("mode", "full (весь трафик)" if c["mode"] == "full" else "split (сети компании)"),
             ("kill-switch", c["killswitch"] and c["mode"] == "full"), ("nat", c["nat"]),
             ("last-handshake", f"{int(time.time() - hs)}s ago" if hs else None),
             ("ipsec", st.get("ipsec_up") if kind == "l2tp" else None),
             ("rx", fmt_bytes(st.get("rx_bytes"))), ("tx", fmt_bytes(st.get("tx_bytes"))),
             ("public-key", st.get("public_key"))])


# --- /system ------------------------------------------------------------------------------------------------------
def resource_print(ctx: Ctx, pos, named):
    r = ctx.api.get("/api/system/resource")
    kv(ctx, [("uptime", fmt_uptime(r["uptime"])), ("version", r["version"]), ("mode", r["mode"]),
             ("board-name", r.get("model")), ("architecture-name", r["arch"]), ("cpu-count", r["cpu_count"]),
             ("cpu-load", f'{r["cpu_percent"]}%' if r["cpu_percent"] is not None else None),
             ("free-memory", fmt_bytes(r["memory"]["total"] - r["memory"]["used"])),
             ("total-memory", fmt_bytes(r["memory"]["total"])),
             ("free-hdd-space", fmt_bytes(r["disk"]["total"] - r["disk"]["used"])),
             ("total-hdd-space", fmt_bytes(r["disk"]["total"])),
             ("temperature", f'{r["temperature"]}C' if r.get("temperature") is not None else None),
             ("kernel", r["kernel"])])


def identity_print(ctx: Ctx, pos, named):
    kv(ctx, [("name", ctx.api.get("/api/system/resource")["identity"])])


def identity_set(ctx: Ctx, pos, named):
    require(named, "name")
    ctx.api.put("/api/system/identity", {"identity": named["name"]})


def system_reboot(ctx: Ctx, pos, named):
    if ctx.confirm("Reboot, yes? [y/N]: "):
        ctx.out(ctx.api.post("/api/system/restart").get("message", "перезапуск"))
        raise Quit()


def system_shell(ctx: Ctx, pos, named):
    if ctx.role != "full":
        raise CliError("not enough permissions (нужна роль full)")
    if not ctx.shell:
        raise CliError("shell недоступен в этом режиме")
    ctx.shell()


def export(ctx: Ctx, pos, named):
    ctx.out(ctx.api.call("GET", "/api/system/backup", raw=True).rstrip())


# --- диагностика (запускается прямо на роутере) -------------------------------------------------------------------
def _run_live(ctx: Ctx, cmd: list[str]) -> None:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except FileNotFoundError:
        raise CliError(f"нет программы {cmd[0]}")
    try:
        for line in proc.stdout:
            ctx.out(line.rstrip())
    except KeyboardInterrupt:          # Ctrl-C — прервать, как в RouterOS
        proc.terminate()
    finally:
        proc.wait()


def _host(pos, named) -> str:
    host = named.get("address") or (pos[0] if pos else "")
    if not host or host.startswith("-") or not all(c.isalnum() or c in ".-:" for c in host):
        raise CliError("укажите адрес: ping 8.8.8.8")
    return host


def _iface(named) -> str | None:
    iface = named.get("interface")
    if iface and (iface.startswith("-") or not all(c.isalnum() or c in "._-@" for c in iface)):
        raise CliError("неверный интерфейс")
    return iface


def ping(ctx: Ctx, pos, named):
    host = _host(pos, named)
    count = int(named.get("count", 4))
    cmd = ["ping", "-6" if ":" in host else "-4", "-n", "-c", str(max(1, min(count, 1000)))]
    if iface := _iface(named):
        cmd += ["-I", iface]
    _run_live(ctx, cmd + [host])


def traceroute(ctx: Ctx, pos, named):
    host = _host(pos, named)
    cmd = ["traceroute", "-I", "-n", "-q", "1", "-w", "2", "-m", str(int(named.get("max-hops", 30)))]
    if iface := _iface(named):
        cmd += ["-i", iface]
    _run_live(ctx, cmd + [host])


def quit_cmd(ctx: Ctx, pos, named):
    raise Quit()


# --- дерево меню -----------------------------------------------------------------------------------------------------
PRINT = "показать"
ROOT = Menu("OutpostGate", {
    "interface": Menu("интерфейсы", {"print": Cmd(interface_print, PRINT)}),
    "ip": Menu("IP", {
        "address": Menu("IP-адреса", {
            "print": Cmd(address_print, PRINT),
            "add": Cmd(address_add, "добавить адрес", ("address", "interface", "comment", "disabled")),
            "remove": Cmd(address_remove, "удалить: remove 0,1", ("numbers",)),
            "enable": Cmd(_toggle("/api/ip/addresses", "/ip address", False), "включить", ("numbers",)),
            "disable": Cmd(_toggle("/api/ip/addresses", "/ip address", True), "выключить", ("numbers",)),
        }),
        "route": Menu("маршруты", {
            "print": Cmd(route_print, PRINT),
            "add": Cmd(route_add, "добавить маршрут", ("dst-address", "gateway", "distance", "comment", "disabled")),
            "remove": Cmd(route_remove, "удалить", ("numbers",)),
            "enable": Cmd(_toggle("/api/ip/routes", "/ip route", False), "включить", ("numbers",)),
            "disable": Cmd(_toggle("/api/ip/routes", "/ip route", True), "выключить", ("numbers",)),
        }),
        "dhcp-server": Menu("DHCP-сервер", {
            "print": Cmd(dhcp_print, PRINT),
            "lease": Menu("аренды и закреплённые адреса", {
                "print": Cmd(lease_print, PRINT),
                "make-static": Cmd(lease_make_static, "закрепить адрес за устройством", ("numbers",)),
                "add": Cmd(lease_add, "закрепить вручную", ("mac-address", "address", "comment")),
                "remove": Cmd(lease_remove, "открепить", ("numbers",)),
            }),
        }),
        "dns": Menu("DNS", {"print": Cmd(dns_print, PRINT)}),
        "firewall": Menu("фаервол", {
            "filter": Menu("правила", {"print": Cmd(filter_print, PRINT)}),
            "nat": Menu("NAT и проброс портов", {"print": Cmd(nat_print, PRINT)}),
        }),
    }),
    "wan": Menu("WAN", {
        "print": Cmd(wan_print, PRINT),
        "set": Cmd(wan_set, "set mode=dhcp | mode=static address=... gateway=... dns=...",
                   ("mode", "address", "gateway", "dns", "interface")),
        "renew": Cmd(wan_renew, "обновить аренду DHCP"),
    }),
    "lan": Menu("LAN", {"print": Cmd(lan_print, PRINT)}),
    "vpn": Menu("VPN", {"print": Cmd(vpn_print, PRINT)}),
    "system": Menu("система", {
        "resource": Menu("ресурсы", {"print": Cmd(resource_print, PRINT)}),
        "identity": Menu("имя роутера", {"print": Cmd(identity_print, PRINT),
                                          "set": Cmd(identity_set, "set name=...", ("name",))}),
        "shell": Cmd(system_shell, "командная строка Linux (bash); назад — exit или Ctrl-D"),
        "reboot": Cmd(system_reboot, "перезапустить сервис роутера"),
    }),
    "ping": Cmd(ping, "ping 8.8.8.8 count=4 interface=wg0", ("count", "interface")),
    "traceroute": Cmd(traceroute, "traceroute 8.8.8.8", ("max-hops", "interface")),
    "export": Cmd(export, "вся конфигурация (router.yaml)"),
    "quit": Cmd(quit_cmd, "выйти"),
})


def node_at(path: list[str]) -> Menu:
    node = ROOT
    for p in path:
        node = node.children[p]
    return node


def path_str(path: list[str]) -> str:
    return "/" + " ".join(path) if path else ""


# --- разбор строки ----------------------------------------------------------------------------------------------------
def parse(line: str, cwd: list[str]) -> tuple[list[str], Cmd | None, list[str]]:
    """-> (путь меню, команда или None, аргументы). Без команды — переход в меню."""
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        raise CliError(f"syntax error ({e})") from e
    if tokens and tokens[0].startswith("/"):          # абсолютный путь: /ip address  или  /ip/address/print
        path = []
        rest = [p for p in tokens[0].split("/") if p] + tokens[1:]
    else:                                             # относительно текущего меню
        path = list(cwd)
        rest = list(tokens)
    while rest:
        w = rest[0]
        if w == "..":
            path = path[:-1]
            rest.pop(0)
            continue
        node = node_at(path)
        child = node.children.get(w)
        if child is None and isinstance(ROOT.children.get(w), Cmd):
            child = ROOT.children[w]          # quit, ping, traceroute, export — из любого меню
        if isinstance(child, Menu):
            path.append(w)
            rest.pop(0)
        elif isinstance(child, Cmd):
            return path, child, rest[1:]
        else:
            raise CliError(f"bad command name {w} (line 1 column {line.find(w) + 1})")
    return path, None, []


def execute(ctx: Ctx, line: str, cwd: list[str]) -> list[str]:
    """Выполнить строку; вернуть новый текущий путь меню."""
    line = line.strip()
    if not line:
        return cwd
    if line in ("?", "help"):
        show_help(ctx, cwd)
        return cwd
    path, cmd, args = parse(line, cwd)
    if cmd is None:
        return path
    pos, named = split_args(args)
    try:
        cmd.fn(ctx, pos, named)
    except ApiError as e:
        raise CliError(f"failure: {e}") from e
    return cwd


def show_help(ctx: Ctx, cwd: list[str]) -> None:
    node = node_at(cwd)
    ctx.out(f"{path_str(cwd) or '/'} — {node.help}")
    for name, child in sorted(node.children.items(), key=lambda kv: (isinstance(kv[1], Cmd), kv[0])):
        mark = "/" if isinstance(child, Menu) else " "
        ctx.out(f"  {mark}{name:<14} {child.help}")
    ctx.out("  .. — на уровень вверх, / — в корень, Tab — подсказки, /system shell — bash, quit — выход")


# --- автодополнение ----------------------------------------------------------------------------------------------------
def complete(text: str, cwd: list[str]) -> list[str]:
    """Варианты для последнего слова строки text (как Tab в RouterOS)."""
    parts = text.split(" ")
    last, head = parts[-1], " ".join(parts[:-1])
    if not head and last.startswith("/"):                      # /ip/addr<Tab>
        segs = last[1:].split("/")
        try:
            node = node_at(segs[:-1])
        except KeyError:
            return []
        base = "/" + "/".join(segs[:-1]) + ("/" if len(segs) > 1 else "")
        return [base + n for n in sorted(node.children) if n.startswith(segs[-1])]
    try:
        path, cmd, args = parse(head, cwd) if head else (list(cwd), None, [])
    except CliError:
        return []
    if cmd is None:
        node = node_at(path)
        return [n for n in sorted(node.children) if n.startswith(last)] + (
            [".."] if path and "..".startswith(last) and last else [])
    used = {a.split("=", 1)[0] for a in args if "=" in a}
    return [p + "=" for p in cmd.params if p not in used and p.startswith(last)]
