"""
VPN → WireGuard (клиент): туннель wg0 к серверу компании.

Маршрутизация:
  full  — маршруты 0.0.0.0/1 и 128.0.0.0/1 через wg0: они точнее маршрута по
          умолчанию и перекрывают его, не удаляя (приём OpenVPN). До самого
          VPN-сервера — отдельный маршрут /32 через шлюз WAN, иначе пакеты
          туннеля ушли бы в сам туннель.
  split — через wg0 только сети компании (AllowedIPs), интернет — напрямую.

Что роутер сделал, записано в data/vpn.json — так выключение убирает ровно своё.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from app.core.config import settings
from app.core.store import store
from app.models.wireguard import WgConfig, WgStatus
from app.services import firewall, netlink, wan

IFACE = "wg0"
ROUTE_METRIC = 1
FULL_ROUTES = ["0.0.0.0/1", "128.0.0.0/1"]
HANDSHAKE_OK = 180   # секунд: WireGuard обновляет handshake каждые 2 минуты

_lock = threading.RLock()


class VpnError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


# --- состояние --------------------------------------------------------------------
def _data(name: str) -> Path:
    return Path(settings.data_dir) / name


def load_state() -> dict:
    try:
        return json.loads(_data("vpn.json").read_text())
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    path = _data("vpn.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".vpn.")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)


def get_config() -> WgConfig:
    return WgConfig.from_yaml(((store.load().get("vpn") or {}).get("wireguard")))


# --- для других модулей ---------------------------------------------------------------
def firewall_rules() -> firewall.VpnRules | None:
    """Правила VPN для фаервола. Kill switch действует, даже если туннель не поднялся."""
    cfg = get_config()
    if not cfg.enabled:
        return None
    return firewall.VpnRules(
        iface=IFACE,
        nat=cfg.nat,
        killswitch=cfg.killswitch and cfg.mode == "full",
        inbound=not cfg.nat,
    )


def dns_override() -> list[str]:
    """DNS туннеля важнее DNS провайдера, когда весь трафик идёт в туннель."""
    st = load_state()
    return st.get("dns", []) if st.get("active") and st.get("mode") == "full" else []


# --- утилита wg -------------------------------------------------------------------
def _wg(*args: str, stdin: str | None = None) -> str:
    try:
        r = subprocess.run(["wg", *args], input=stdin, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as e:
        raise VpnError(500, "нет утилиты wg (пакет wireguard-tools) — пересоберите образ") from e
    if r.returncode != 0:
        raise VpnError(400, f"wg {args[0]}: {r.stderr.strip()}")
    return r.stdout.strip()


def genkey() -> tuple[str, str]:
    private = _wg("genkey")
    return private, _wg("pubkey", stdin=private + "\n")


def wg_conf(cfg: WgConfig, endpoint_ip: str) -> str:
    """Конфиг для `wg setconf` (без Address/DNS/MTU — их ставит роутер)."""
    _, port = cfg.endpoint_host_port()
    allowed = "0.0.0.0/0" if cfg.mode == "full" else ", ".join(cfg.split_networks())
    lines = ["[Interface]", f"PrivateKey = {cfg.private_key}", "", "[Peer]",
             f"PublicKey = {cfg.peer_public_key}"]
    if cfg.preshared_key:
        lines.append(f"PresharedKey = {cfg.preshared_key}")
    lines += [f"Endpoint = {endpoint_ip}:{port}", f"AllowedIPs = {allowed}"]
    if cfg.keepalive:
        lines.append(f"PersistentKeepalive = {cfg.keepalive}")
    return "\n".join(lines) + "\n"


def resolve_endpoint(cfg: WgConfig) -> str:
    host, port = cfg.endpoint_host_port()
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM)
    except socket.gaierror as e:
        raise VpnError(400, f"не удалось определить адрес сервера {host}: {e}") from e
    return infos[0][4][0]


# --- маршрут до VPN-сервера ---------------------------------------------------------------
def refresh_endpoint_route() -> None:
    """Маршрут /32 до сервера через текущий шлюз WAN. Вызывается и после новой аренды DHCP."""
    with _lock:
        st = load_state()
        if not st.get("active") or not st.get("endpoint_ip"):
            return
        gw = wan.current_gateway()
        new = [f"{st['endpoint_ip']}/32", gw] if gw else None
        old = st.get("endpoint_route")
        if old and old != new:
            try:
                netlink.route_del(old[0], old[1], None, ROUTE_METRIC)
            except netlink.NetlinkOpError as e:
                print(f"[vpn] WARNING: {e}")
        if new:
            try:
                netlink.route_add(new[0], new[1], None, ROUTE_METRIC)
            except netlink.NetlinkOpError as e:
                print(f"[vpn] WARNING: маршрут до сервера: {e}")
                new = None
        st["endpoint_route"] = new
        save_state(st)


# --- применение ------------------------------------------------------------------------------
def teardown(state: dict) -> None:
    if state.get("endpoint_route"):
        try:
            netlink.route_del(*state["endpoint_route"], None, ROUTE_METRIC)
        except netlink.NetlinkOpError as e:
            print(f"[vpn] WARNING: {e}")
    netlink.link_delete(IFACE)          # вместе с wg0 уходят его адреса и маршруты
    save_state({})


def _check_networks(cfg: WgConfig) -> None:
    from app.services import lan
    lan_cfg = lan.get_config()
    if not lan_cfg.enabled:
        return
    lan_net = ipaddress.ip_interface(lan_cfg.address).network
    for n in cfg.split_networks() + [str(ipaddress.ip_interface(a).network) for a in cfg.addresses]:
        if ipaddress.ip_network(n).overlaps(lan_net):
            raise VpnError(400, f"сеть {n} пересекается с LAN {lan_net}: у каждого роутера "
                                f"должна быть своя подсеть LAN")


def setup(cfg: WgConfig) -> None:
    if not cfg.private_key:
        raise VpnError(400, "нет PrivateKey: импортируйте конфиг или сгенерируйте ключи")
    _check_networks(cfg)
    endpoint_ip = resolve_endpoint(cfg)

    netlink.wireguard_create(IFACE)
    state: dict = {"active": False, "mode": cfg.mode, "endpoint_ip": endpoint_ip, "dns": cfg.dns}
    save_state(state)

    conf = _data("wg0.conf")
    conf.write_text(wg_conf(cfg, endpoint_ip))
    os.chmod(conf, 0o600)                # в файле приватный ключ
    _wg("setconf", IFACE, str(conf))

    for a in cfg.addresses:
        netlink.addr_add(IFACE, a)
    netlink.link_set_mtu(IFACE, cfg.mtu)
    netlink.link_set_up(IFACE)
    state["active"] = True
    save_state(state)

    refresh_endpoint_route()             # сначала дорога до сервера, потом весь трафик в туннель
    for dst in (FULL_ROUTES if cfg.mode == "full" else cfg.split_networks()):
        netlink.route_add(dst, None, IFACE, ROUTE_METRIC)
    print(f"[vpn] WireGuard {IFACE} -> {cfg.endpoint} ({endpoint_ip}), режим {cfg.mode}")


def apply(cfg: WgConfig) -> None:
    with _lock:
        teardown(load_state())
        try:
            if cfg.enabled:
                setup(cfg)
        finally:                         # фаервол и DNS — в любом случае (kill switch!)
            _refresh_neighbours()


def _refresh_neighbours() -> None:
    try:
        firewall.refresh()
    except firewall.FirewallError as e:
        print(f"[vpn] ERROR: фаервол: {e}")
    wan.refresh_upstream_dns()


def update(new: WgConfig) -> WgStatus:
    old = get_config()
    if not new.private_key:
        new = new.model_copy(update={"private_key": old.private_key})   # пусто = не менять
    try:
        new = WgConfig.model_validate(new.model_dump())
    except ValueError as e:
        raise VpnError(422, str(e)) from e
    try:
        _save(new)                       # сначала конфиг: фаервол читает kill switch из него
        apply(new)
    except (netlink.NetlinkOpError, VpnError) as e:
        _save(old)
        try:
            apply(old)
        except Exception as rollback_err:
            print(f"[vpn] ERROR: откат не удался: {rollback_err}")
        if isinstance(e, VpnError):
            raise
        raise VpnError(400, str(e)) from e
    return status()


def _save(cfg: WgConfig) -> None:
    with store.transaction() as data:
        vpn = data.get("vpn") or {}
        vpn["wireguard"] = cfg.to_yaml()
        data["vpn"] = vpn


def on_wan_changed() -> None:
    refresh_endpoint_route()


def apply_startup() -> None:
    cfg = get_config()
    try:
        apply(cfg)
    except (netlink.NetlinkOpError, VpnError) as e:
        print(f"[vpn] ERROR: {e}")


# --- статус ----------------------------------------------------------------------------------
def status() -> WgStatus:
    cfg = get_config()
    st = load_state()
    out = WgStatus(
        config=cfg.model_copy(update={"private_key": None}),
        private_key_set=bool(cfg.private_key),
        endpoint_ip=st.get("endpoint_ip"),
        active=bool(st.get("active")) and IFACE in netlink.link_names(),
    )
    try:
        if cfg.private_key:
            out.public_key = _wg("pubkey", stdin=cfg.private_key + "\n")
        if out.active:
            lines = _wg("show", IFACE, "dump").splitlines()
            if len(lines) > 1:
                peer = lines[1].split("\t")
                handshake = int(peer[4])
                out.latest_handshake = handshake or None
                out.rx_bytes, out.tx_bytes = int(peer[5]), int(peer[6])
                out.connected = bool(handshake) and time.time() - handshake < HANDSHAKE_OK
    except VpnError as e:
        out.error = e.message
    return out
