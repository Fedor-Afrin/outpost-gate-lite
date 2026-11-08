"""
Базовый фаервол и NAT (nftables).

Свою таблицу `inet ubuntu_router` роутер генерирует целиком и применяет
атомарно (`nft -f`): либо применяется вся, либо ничего. Чужие таблицы
(Docker, системные) не трогаются.

  input   — с WAN: только ответы, ICMP, DHCP и (по галочке) управление;
            из VPN: всё (site-to-site) или только ответы (режим NAT)
  forward — LAN → WAN (если нет kill switch), LAN → VPN; WAN → LAN закрыто
  NAT     — masquerade в WAN; в VPN — по настройке туннеля
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

TABLE = "ubuntu_router"
SSH_PORT = 22


class FirewallError(Exception):
    pass


@dataclass
class VpnRules:
    iface: str            # wg0
    nat: bool             # masquerade LAN за адресом туннеля
    killswitch: bool      # LAN → WAN напрямую запрещено (весь трафик только в туннель)
    inbound: bool         # из туннеля можно заходить в LAN и на роутер (site-to-site)


def management_ports() -> list[int]:
    return sorted({int(os.getenv("API_PORT", "8000")), SSH_PORT})


def ruleset(wan: str, lan: str, wan_management: bool, vpn: VpnRules | None = None) -> str:
    mgmt = ", ".join(str(p) for p in management_ports())
    i = " " * 8
    input_vpn = forward = post = ""
    mgmt_rule = f'{i}tcp dport {{ {mgmt} }} accept   # управление с WAN (веб, SSH)\n' if wan_management else ""

    if vpn and not vpn.inbound:
        input_vpn = f'{i}iifname "{vpn.iface}" drop            # из туннеля — только ответы\n'

    if vpn:
        forward += (f'{i}oifname "{vpn.iface}" tcp flags syn tcp option maxseg size set rt mtu\n'
                    f'{i}iifname "{vpn.iface}" tcp flags syn tcp option maxseg size set rt mtu\n')
    forward += f'{i}ct state established,related accept\n{i}ct state invalid drop\n'
    if vpn and vpn.killswitch:
        forward += f'{i}# kill switch: LAN → WAN напрямую запрещено, только через туннель\n'
    else:
        forward += f'{i}iifname "{lan}" oifname "{wan}" accept\n'
    if vpn:
        forward += f'{i}iifname "{lan}" oifname "{vpn.iface}" accept\n'
        if vpn.inbound:
            forward += f'{i}iifname "{vpn.iface}" oifname "{lan}" accept   # центр видит устройства LAN\n'

    post = f'{i}oifname "{wan}" masquerade\n'
    if vpn and vpn.nat:
        post += f'{i}oifname "{vpn.iface}" masquerade\n'

    return f"""# сгенерировано Ubuntu Router — не редактировать вручную
add table inet {TABLE}
delete table inet {TABLE}

table inet {TABLE} {{
    chain input {{
        type filter hook input priority filter; policy accept;
        ct state established,related accept
        ct state invalid drop
        iifname "lo" accept
{input_vpn}        iifname != "{wan}" accept            # LAN — без ограничений
        ip protocol icmp accept
        udp sport 67 udp dport 68 accept     # ответы DHCP-сервера провайдера
{mgmt_rule}        drop                                 # всё остальное с WAN
    }}

    chain forward {{
        type filter hook forward priority filter; policy drop;
{forward}    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
{post}    }}
}}
"""


def apply(wan: str, lan: str, wan_management: bool, vpn: VpnRules | None = None) -> None:
    text = ruleset(wan, lan, wan_management, vpn)
    try:
        r = subprocess.run(["nft", "-f", "-"], input=text, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as e:
        raise FirewallError("нет программы nft (пакет nftables)") from e
    if r.returncode != 0:
        raise FirewallError(f"nft: {r.stderr.strip()}")
    print(f"[firewall] применён: WAN={wan} LAN={lan} управление с WAN={'да' if wan_management else 'нет'}"
          + (f" VPN={vpn.iface} NAT={'да' if vpn.nat else 'нет'} kill switch={'да' if vpn.killswitch else 'нет'}"
             if vpn else ""))


def refresh(lan_cfg=None) -> None:
    """Собрать правила из текущего состояния LAN, WAN и VPN и применить.

    lan_cfg — новые настройки LAN, если они применяются прямо сейчас и ещё не сохранены.
    """
    from app.services import lan, vpn   # здесь, чтобы не было циклического импорта
    cfg = lan_cfg or lan.get_config()
    wan_if = lan.wan_interface()
    if not (cfg.enabled and lan.load_state().get("address") and wan_if):
        remove()   # фаервол работает вместе с LAN
        return
    apply(wan_if, lan.BRIDGE, cfg.wan_management, vpn.firewall_rules())


def remove() -> None:
    try:
        subprocess.run(["nft", "delete", "table", "inet", TABLE], capture_output=True, timeout=10)
    except FileNotFoundError:
        pass
