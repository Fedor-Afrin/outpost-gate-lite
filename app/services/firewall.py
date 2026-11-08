"""
Базовый фаервол и NAT (nftables).

Свою таблицу `inet ubuntu_router` роутер генерирует целиком и применяет
атомарно (`nft -f`): либо применяется вся, либо ничего. Чужие таблицы
(Docker, системные) не трогаются.

  input   — с WAN: только ответы, ICMP, DHCP и (по галочке) управление
  forward — LAN → WAN разрешено, WAN → LAN закрыто
  NAT     — masquerade всего, что уходит в WAN
"""
from __future__ import annotations

import os
import subprocess

TABLE = "ubuntu_router"
SSH_PORT = 22


class FirewallError(Exception):
    pass


def management_ports() -> list[int]:
    return sorted({int(os.getenv("API_PORT", "8000")), SSH_PORT})


def ruleset(wan: str, lan: str, wan_management: bool) -> str:
    mgmt = ", ".join(str(p) for p in management_ports())
    mgmt_rule = (f"        tcp dport {{ {mgmt} }} accept   # управление с WAN (веб, SSH)\n"
                 if wan_management else "")
    return f"""# сгенерировано Ubuntu Router — не редактировать вручную
add table inet {TABLE}
delete table inet {TABLE}

table inet {TABLE} {{
    chain input {{
        type filter hook input priority filter; policy accept;
        ct state established,related accept
        ct state invalid drop
        iifname "lo" accept
        iifname != "{wan}" accept            # LAN и прочие — без ограничений
        ip protocol icmp accept
        udp sport 67 udp dport 68 accept     # ответы DHCP-сервера провайдера
{mgmt_rule}        drop                                 # всё остальное с WAN
    }}

    chain forward {{
        type filter hook forward priority filter; policy drop;
        ct state established,related accept
        ct state invalid drop
        iifname "{lan}" oifname "{wan}" accept
    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
        oifname "{wan}" masquerade
    }}
}}
"""


def apply(wan: str, lan: str, wan_management: bool) -> None:
    text = ruleset(wan, lan, wan_management)
    try:
        r = subprocess.run(["nft", "-f", "-"], input=text, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as e:
        raise FirewallError("нет программы nft (пакет nftables)") from e
    if r.returncode != 0:
        raise FirewallError(f"nft: {r.stderr.strip()}")
    print(f"[firewall] применён: WAN={wan} LAN={lan} управление с WAN={'да' if wan_management else 'нет'}")


def remove() -> None:
    try:
        subprocess.run(["nft", "delete", "table", "inet", TABLE], capture_output=True, timeout=10)
    except FileNotFoundError:
        pass
