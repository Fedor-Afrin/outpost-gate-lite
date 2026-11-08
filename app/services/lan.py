"""
LAN — все порты, кроме WAN, в мосту br-lan; dnsmasq раздаёт адреса и DNS; NAT в WAN.

Как и WAN, LAN записывает в data/lan.json, что именно он сделал (какие порты
забрал в мост, какие адреса перенёс с портов на мост), чтобы при выключении
или смене настроек вернуть всё как было.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.core.store import store
from app.models.lan import LanConfig, LanStatus, Lease, Port
from app.services import firewall, netlink, oui, wan

BRIDGE = "br-lan"

_lock = threading.RLock()
_dnsmasq: subprocess.Popen | None = None


class LanError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --- файлы ---------------------------------------------------------------------------
def _data(name: str) -> Path:
    return Path(settings.data_dir) / name


def state_file() -> Path:
    return _data("lan.json")


def load_state() -> dict:
    try:
        return json.loads(state_file().read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".lan.")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def get_config() -> LanConfig:
    data = store.load()
    return LanConfig.from_yaml(data.get("lan"), data.get("firewall"))


# --- dnsmasq ---------------------------------------------------------------------------
def dnsmasq_conf(cfg: LanConfig, leases_file: str, resolv_file: str) -> str:
    iface = ipaddress.ip_interface(cfg.address)
    lines = [
        "# сгенерировано Ubuntu Router — не редактировать вручную",
        "keep-in-foreground",
        "log-facility=-",            # журнал — в docker logs
        "pid-file=",
        "user=root",
        f"interface={BRIDGE}",
        "bind-dynamic",              # слушать только адрес моста, порт 53 хоста не занимаем
        "",
        "# --- DNS ---",
        f"resolv-file={resolv_file}",   # вышестоящие DNS от WAN, файл обновляется на лету
        "domain-needed",
        "bogus-priv",
        "cache-size=1000",
        "domain=lan",
        "local=/lan/",
        "expand-hosts",
        "",
    ]
    if cfg.dhcp_enabled:
        lines += [
            "# --- DHCP ---",
            f"dhcp-range={cfg.pool_start},{cfg.pool_end},{iface.network.netmask},{cfg.lease_time}",
            f"dhcp-option=option:router,{iface.ip}",
            f"dhcp-option=option:dns-server,{iface.ip}",
            f"dhcp-leasefile={leases_file}",
            "dhcp-authoritative",
            "dhcp-rapid-commit",
        ]
    else:
        lines.append(f"no-dhcp-interface={BRIDGE}")
    return "\n".join(lines) + "\n"


def dnsmasq_running() -> bool:
    return _dnsmasq is not None and _dnsmasq.poll() is None


def start_dnsmasq(cfg: LanConfig) -> None:
    global _dnsmasq
    conf = _data("dnsmasq.conf")
    if not wan.resolv_file().exists():
        wan.write_upstream_dns(wan.get_config().dns)
    conf.write_text(dnsmasq_conf(cfg, str(_data("dnsmasq.leases")), str(wan.resolv_file())))
    try:
        _dnsmasq = subprocess.Popen(["dnsmasq", f"--conf-file={conf}"])
    except FileNotFoundError as e:
        raise LanError(500, "нет dnsmasq — пересоберите образ") from e
    print(f"[lan] dnsmasq запущен (pid {_dnsmasq.pid})")


def stop_dnsmasq() -> None:
    global _dnsmasq
    if dnsmasq_running():
        _dnsmasq.terminate()
        try:
            _dnsmasq.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _dnsmasq.kill()
            _dnsmasq.wait()
        print("[lan] dnsmasq остановлен")
    _dnsmasq = None


def leases() -> list[Lease]:
    """Формат файла dnsmasq: <срок> <MAC> <IP> <имя|*> <client-id|*>"""
    try:
        lines = _data("dnsmasq.leases").read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        parts = line.split()
        if len(parts) < 4:
            continue
        expiry, mac, ip, name = parts[:4]
        out.append(Lease(
            ip=ip, mac=mac,
            hostname=None if name == "*" else name,
            vendor=oui.vendor(mac),
            expires=None if expiry == "0" else float(expiry),
        ))
    return sorted(out, key=lambda l: tuple(int(x) for x in l.ip.split(".")))


# --- порты -------------------------------------------------------------------------
def wan_interface() -> str | None:
    try:
        return wan.load_state().get("interface") or wan.resolve_interface(wan.get_config())
    except wan.WanError:
        return None


def lan_ports(cfg: LanConfig, wan_if: str | None) -> list[str]:
    existing = set(wan.candidates())
    if cfg.ports:
        return [p for p in cfg.ports if p in existing and p != wan_if]
    return [p for p in sorted(existing) if p != wan_if]


def _check_overlap(cfg: LanConfig, wan_if: str | None) -> None:
    lan_net = ipaddress.ip_interface(cfg.address).network
    for ifname, cidr in netlink.kernel_ipv4_addresses():
        if ifname == wan_if and ipaddress.ip_interface(cidr).network.overlaps(lan_net):
            raise LanError(400, f"сеть LAN {lan_net} пересекается с адресом на WAN ({wan_if}: {cidr}). "
                                f"Выберите другую сеть LAN или уберите адрес в Advanced → IP Addresses")


def _wait_for_ports(seconds: float = 5.0) -> None:
    """В GNS3 интерфейсы появляются не сразу: ждём, пока их число перестанет меняться."""
    deadline = time.monotonic() + seconds
    last, stable_since = None, time.monotonic()
    while time.monotonic() < deadline:
        now = len(wan.candidates())
        if now != last:
            last, stable_since = now, time.monotonic()
        elif time.monotonic() - stable_since >= 1.0:
            return
        time.sleep(0.25)


# --- применение ------------------------------------------------------------------------
def teardown(state: dict) -> None:
    """Вернуть всё, как было до включения LAN."""
    stop_dnsmasq()
    firewall.remove()
    if state.get("address"):
        try:
            netlink.addr_del(BRIDGE, state["address"])
        except netlink.NetlinkOpError as e:
            print(f"[lan] WARNING: {e}")
    for port in state.get("ports", []):
        try:
            netlink.link_set_master(port, None)
        except netlink.NetlinkOpError as e:
            print(f"[lan] WARNING: {e}")
    for port, cidr in state.get("moved", []):
        try:
            netlink.addr_add(port, cidr)
        except netlink.NetlinkOpError as e:
            print(f"[lan] WARNING: {e}")
    if state.get("bridge"):
        netlink.link_delete(BRIDGE)
    save_state({})


def setup(cfg: LanConfig) -> None:
    wan_if = wan_interface()
    if not wan_if:
        raise LanError(400, "сначала нужен WAN: интерфейс WAN не найден")
    _check_overlap(cfg, wan_if)
    ports = lan_ports(cfg, wan_if)

    state: dict = {"bridge": True, "ports": [], "moved": [], "address": None}
    mac = netlink.link_info(ports[0]).get("mac") if ports else None
    netlink.bridge_create(BRIDGE, mac)
    save_state(state)

    for port in ports:
        # адреса порта переезжают на мост (иначе порт моста с IP работает некорректно)
        for ifname, cidr in netlink.kernel_ipv4_addresses():
            if ifname == port:
                netlink.addr_del(port, cidr)
                state["moved"].append([port, cidr])
                netlink.addr_add(BRIDGE, cidr)
        netlink.link_set_master(port, BRIDGE)
        netlink.link_set_up(port)
        state["ports"].append(port)
        save_state(state)

    netlink.link_set_up(BRIDGE)
    netlink.addr_add(BRIDGE, cfg.address)
    state["address"] = cfg.address
    save_state(state)

    start_dnsmasq(cfg)
    try:
        firewall.apply(wan_if, BRIDGE, cfg.wan_management)
    except firewall.FirewallError as e:
        raise LanError(500, str(e)) from e
    print(f"[lan] {BRIDGE} {cfg.address}, порты: {', '.join(ports) or 'нет'}")


def apply(cfg: LanConfig) -> None:
    with _lock:
        teardown(load_state())
        if cfg.enabled:
            setup(cfg)


def update(new: LanConfig) -> LanStatus:
    old = get_config()
    try:
        apply(new)
    except (netlink.NetlinkOpError, LanError) as e:
        try:
            apply(old)
        except Exception as rollback_err:
            print(f"[lan] ERROR: откат не удался: {rollback_err}")
        if isinstance(e, LanError):
            raise
        raise LanError(400, str(e)) from e
    lan_yaml, fw_yaml = new.to_yaml()
    with store.transaction() as cfg:
        cfg["lan"] = lan_yaml
        cfg.setdefault("firewall", {})
        cfg["firewall"] = {**(cfg["firewall"] or {}), **fw_yaml}
    return status()


def on_wan_changed() -> None:
    """WAN поменялся (интерфейс или режим) — пересобрать LAN, NAT и фаервол."""
    cfg = get_config()
    if cfg.enabled:
        try:
            apply(cfg)
        except (netlink.NetlinkOpError, LanError) as e:
            print(f"[lan] ERROR после смены WAN: {e}")


def apply_startup() -> None:
    cfg = get_config()
    if not cfg.enabled:
        teardown(load_state())   # остатки от прошлого запуска (режим host)
        return
    _wait_for_ports()
    apply(cfg)


# --- статус ----------------------------------------------------------------------------
def status() -> LanStatus:
    cfg = get_config()
    st = load_state()
    wan_if = wan_interface()
    in_lan = set(st.get("ports", []))

    ports = []
    for name in sorted(set(wan.candidates()) | in_lan):
        info = netlink.link_info(name)
        role = "wan" if name == wan_if else ("lan" if name in in_lan else "none")
        ports.append(Port(name=name, role=role, **info))
    ports.sort(key=lambda p: (p.role != "wan", p.name))

    active = bool(st.get("address")) and (BRIDGE, st["address"]) in set(netlink.kernel_ipv4_addresses())
    return LanStatus(
        config=cfg,
        active=active,
        bridge=BRIDGE,
        wan_interface=wan_if,
        ports=ports,
        dns_dhcp_running=dnsmasq_running(),
        leases=leases(),
    )
