"""
Фаервол и NAT (nftables).

Свою таблицу `inet outpost_gate_lite` роутер генерирует целиком и применяет
атомарно (`nft -f`): либо применяется вся, либо ничего. Чужие таблицы
(Docker, системные) не трогаются.

Порядок в каждой цепочке:
  1. служебное: ответы (established), мусор (invalid), loopback
  2. ПРАВИЛА ПОЛЬЗОВАТЕЛЯ — сверху вниз, первое совпавшее решает
  3. системные правила: LAN, VPN, IPsec, управление, kill switch
  4. политика по умолчанию (input с WAN и forward — drop)

  input   — с WAN: только ответы, ICMP, DHCP и (по галочке) управление;
            из VPN: всё (site-to-site) или только ответы (режим NAT)
  forward — LAN → WAN (если нет kill switch), LAN → VPN; WAN → LAN закрыто
  NAT     — masquerade в WAN; в VPN — по настройке туннеля; проброс портов (DNAT)
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

from app.models.firewall import FirewallRule, PortForward, port_set

TABLE = "outpost_gate_lite"
LEGACY_TABLES = ("ubuntu_router", "outpost_gate")   # таблицы под прежними названиями проекта — удаляются
I = " " * 8


class FirewallError(Exception):
    pass


@dataclass
class VpnRules:
    iface: str            # wg0 / awg0 / l2tp0
    nat: bool             # masquerade LAN за адресом туннеля
    killswitch: bool      # LAN → WAN напрямую запрещено (весь трафик только в туннель)
    inbound: bool         # из туннеля можно заходить в LAN и на роутер (site-to-site)
    ipsec_server: str | None = None   # L2TP/IPsec: впустить с WAN IKE, ESP и L2TP от этого сервера
    management: bool = False          # из туннеля можно на роутер: веб, SSH, CLI, ping (при NAT)
    router_direct: bool = False       # режим full: свои соединения роутера — мимо туннеля (метка BYPASS)
    tunnel_dns: tuple = ()            # DNS туннеля — к ним роутер ходит через туннель


def management_ports() -> list[int]:
    """Веб/API и SSH-доступ к CLI роутера; в режиме host — и SSH самого сервера (HOST_SSH_PORT)."""
    ports = {int(os.getenv("API_PORT", "80")), int(os.getenv("CLI_SSH_PORT", "22"))}
    host_ssh = os.getenv("HOST_SSH_PORT", "")
    if host_ssh.isdigit():
        ports.add(int(host_ssh))
    return sorted(ports)


# --- правила пользователя -> nft ------------------------------------------------------
def render_rule(rule: FirewallRule, rid: int, ifaces: dict[str, str | None]) -> str:
    """Одна строка nft; если зона сейчас недоступна (VPN выключен) — закомментированная."""
    parts = []
    for zone, key in ((rule.in_zone, "iifname"), (rule.out_zone, "oifname")):
        if zone != "any":
            iface = ifaces.get(zone)
            if not iface:
                return f"{I}# rule:{rid} пропущено — зона {zone} сейчас не активна\n"
            parts.append(f'{key} "{iface}"')
    if rule.src:
        parts.append(f"ip saddr {rule.src}")
    if rule.dst:
        parts.append(f"ip daddr {rule.dst}")
    if rule.protocol == "icmp":
        parts.append("ip protocol icmp")
    elif rule.protocol in ("tcp", "udp"):
        if rule.src_ports:
            parts.append(f"{rule.protocol} sport {port_set(rule.src_ports)}")
        if rule.dst_ports:
            parts.append(f"{rule.protocol} dport {port_set(rule.dst_ports)}")
        if not rule.src_ports and not rule.dst_ports:
            parts.append(f"meta l4proto {rule.protocol}")
    parts += ["counter", rule.action, f'comment "rule:{rid}"']
    return I + " ".join(parts) + "\n"


def render_forward(fwd: PortForward, fid: int, wan: str, vpn_iface: str | None = None) -> str:
    """Проброс: с WAN, из VPN-туннеля (к устройству LAN с телефона через тот же сервер) или с обоих."""
    zone = getattr(fwd, "from_zone", "wan")
    ifaces = ([wan] if zone in ("wan", "any") else []) + ([vpn_iface] if zone in ("vpn", "any") and vpn_iface else [])
    if not ifaces:
        return ""                                # проброс из VPN, а туннель выключен
    iif = f'"{ifaces[0]}"' if len(ifaces) == 1 else "{ " + ", ".join(f'"{n}"' for n in ifaces) + " }"
    proto = "{ tcp, udp }" if fwd.protocol == "tcp+udp" else fwd.protocol
    src = f"ip saddr {fwd.src} " if fwd.src else ""
    target = fwd.to_ip + (f":{fwd.to_port}" if fwd.to_port else "")
    return (f'{I}iifname {iif} {src}meta l4proto {proto} th dport {fwd.wan_port} '
            f'counter dnat ip to {target} comment "fwd:{fid}"\n')


# --- весь ruleset ---------------------------------------------------------------------
def ruleset(wan: str, lan: str, wan_management: bool, vpn: VpnRules | None = None,
            rules: list[tuple[int, FirewallRule]] = (), forwards: list[tuple[int, PortForward]] = ()) -> str:
    ifaces = {"wan": wan, "lan": lan, "vpn": vpn.iface if vpn else None}
    user_in = "".join(render_rule(r, rid, ifaces) for rid, r in rules if r.enabled and r.chain == "input")
    user_fwd = "".join(render_rule(r, rid, ifaces) for rid, r in rules if r.enabled and r.chain == "forward")
    active_fwd = [(fid, f) for fid, f in forwards if f.enabled]
    dnat = "".join(render_forward(f, fid, wan, vpn.iface if vpn else None) for fid, f in active_fwd)

    mgmt = ", ".join(str(p) for p in management_ports())
    mgmt_rule = f'{I}tcp dport {{ {mgmt} }} accept   # управление с WAN (веб, SSH)\n' if wan_management else ""
    input_vpn = ""
    if vpn and not vpn.inbound:
        if vpn.management:
            input_vpn += (f'{I}iifname "{vpn.iface}" tcp dport {{ {mgmt} }} accept   # управление через туннель\n'
                          f'{I}iifname "{vpn.iface}" icmp type echo-request accept\n')
        input_vpn += f'{I}iifname "{vpn.iface}" drop            # из туннеля — только ответы\n'
    ipsec_rules = ""
    if vpn and vpn.ipsec_server:
        srv = vpn.ipsec_server
        ipsec_rules = (f'{I}ip saddr {srv} udp dport {{ 500, 4500 }} accept   # IKE от сервера L2TP/IPsec\n'
                       f'{I}ip saddr {srv} ip protocol esp accept\n'
                       f'{I}ip saddr {srv} udp dport 1701 accept           # L2TP (внутри IPsec)\n')

    forward = ""
    if vpn:
        forward += (f'{I}oifname "{vpn.iface}" tcp flags syn tcp option maxseg size set rt mtu\n'
                    f'{I}iifname "{vpn.iface}" tcp flags syn tcp option maxseg size set rt mtu\n')
    forward += f'{I}ct state established,related accept\n{I}ct state invalid drop\n'
    forward += user_fwd and f"{I}# --- правила пользователя ---\n{user_fwd}{I}# --- системные ---\n"
    if active_fwd:
        forward += f'{I}ct status dnat accept               # проброс портов\n'
    if vpn and vpn.killswitch:
        forward += f'{I}# kill switch: LAN → WAN напрямую запрещено, только через туннель\n'
    else:
        forward += f'{I}iifname "{lan}" oifname "{wan}" accept\n'
    if vpn:
        forward += f'{I}iifname "{lan}" oifname "{vpn.iface}" accept\n'
        if vpn.inbound:
            forward += f'{I}iifname "{vpn.iface}" oifname "{lan}" accept   # центр видит устройства LAN\n'

    post = f'{I}oifname "{wan}" masquerade\n'
    if vpn and vpn.nat:
        post += f'{I}oifname "{vpn.iface}" masquerade\n'

    user_in_block = user_in and f"{I}# --- правила пользователя ---\n{user_in}{I}# --- системные ---\n"
    legacy = "".join(f"add table inet {t}\ndelete table inet {t}\n" for t in LEGACY_TABLES)
    return f"""# сгенерировано OutpostGate Lite — не редактировать вручную
{legacy}add table inet {TABLE}
delete table inet {TABLE}

table inet {TABLE} {{
    chain input {{
        type filter hook input priority filter; policy accept;
        ct state established,related accept
        ct state invalid drop
        iifname "lo" accept
{user_in_block}{input_vpn}        iifname != "{wan}" accept            # LAN — без ограничений
        ip protocol icmp accept
        udp sport 67 udp dport 68 accept     # ответы DHCP-сервера провайдера
{ipsec_rules}{mgmt_rule}        drop                                 # всё остальное с WAN
    }}

    chain forward {{
        type filter hook forward priority filter; policy drop;
{forward}    }}

    chain prerouting {{
        type nat hook prerouting priority dstnat; policy accept;
{dnat}    }}

    chain postrouting {{
        type nat hook postrouting priority srcnat; policy accept;
{post}    }}
{render_router_direct(vpn)}}}
"""


PRIVATE_NETS = "10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 127.0.0.0/8, 169.254.0.0/16, " \
               "224.0.0.0/4, 255.255.255.255"


def render_router_direct(vpn: "VpnRules | None") -> str:
    """Режим full: соединения, начатые самим роутером, к публичным адресам — с меткой 0x200
    (ip rule отправит их через WAN). Ответы на входящие (управление через туннель), частные сети,
    DNS туннеля и ICMP (ping/traceroute проверяют туннель) — без метки, как раньше."""
    if not vpn or not vpn.router_direct:
        return ""
    dns = ", ".join(vpn.tunnel_dns)
    skip_dns = f"{I}ip daddr {{ {dns} }} return\n" if dns else ""
    return f"""
    chain output_direct {{
        type route hook output priority mangle; policy accept;
{I}ct direction reply return
{I}meta l4proto {{ icmp, ipv6-icmp }} return
{I}ip daddr {{ {PRIVATE_NETS} }} return
{skip_dns}{I}meta nfproto ipv4 meta mark set meta mark or 0x200   # трафик самого роутера — через WAN
    }}
"""


def system_rules(wan: str | None, wan_management: bool, vpn: VpnRules | None) -> dict[str, list[str]]:
    """То же, что делают системные правила, — человеческим языком (для веб-интерфейса)."""
    mgmt = ", ".join(str(p) for p in management_ports())
    inp = ["Ответы на соединения, начатые роутером, — разрешены",
           "Из LAN — разрешено всё"]
    if vpn:
        inp.append(f"Из VPN ({vpn.iface}) — " + ("разрешено всё (site-to-site)" if vpn.inbound
                                                 else f"управление (порты {mgmt}) и ping, остальное — только ответы"
                                                 if vpn.management else "только ответы (режим NAT)"))
    if vpn and vpn.router_direct:
        inp.append("Свои соединения роутера (обновления, Docker Hub, apt) — напрямую через WAN, не через VPN; "
                   "ping и DNS туннеля — через туннель")
    inp.append(f"С WAN ({wan}): ping и DHCP" + (f", управление (порты {mgmt})" if wan_management else ""))
    if vpn and vpn.ipsec_server:
        inp.append(f"С WAN от сервера L2TP {vpn.ipsec_server}: IKE, ESP, L2TP")
    inp.append("Всё остальное с WAN — запрещено")

    fwd = ["Ответы на разрешённые соединения — разрешены"]
    fwd.append("LAN → WAN — " + ("запрещено (kill switch)" if vpn and vpn.killswitch else "разрешено"))
    if vpn:
        fwd.append(f"LAN → VPN ({vpn.iface}) — разрешено")
        if vpn.inbound:
            fwd.append(f"VPN → LAN — разрешено (site-to-site)")
    fwd.append("WAN → LAN — запрещено (кроме проброса портов)")

    nat = [f"Masquerade в WAN ({wan})"]
    if vpn and vpn.nat:
        nat.append(f"Masquerade в VPN ({vpn.iface})")
    return {"input": inp, "forward": fwd, "nat": nat}


# --- применение -----------------------------------------------------------------------
def _nft(args: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["nft", *args], input=stdin, capture_output=True, text=True, timeout=10)
    except FileNotFoundError as e:
        raise FirewallError("нет программы nft (пакет nftables)") from e


def apply_text(text: str) -> None:
    r = _nft(["-f", "-"], stdin=text)
    if r.returncode != 0:
        raise FirewallError(f"nft: {r.stderr.strip()}")


def apply(wan: str, lan: str, wan_management: bool, vpn: VpnRules | None = None,
          rules=(), forwards=()) -> None:
    apply_text(ruleset(wan, lan, wan_management, vpn, rules, forwards))
    print(f"[firewall] применён: WAN={wan} LAN={lan} управление с WAN={'да' if wan_management else 'нет'}"
          + (f" VPN={vpn.iface} NAT={'да' if vpn.nat else 'нет'} kill switch={'да' if vpn.killswitch else 'нет'}"
             if vpn else "")
          + f" правил: {len(rules)}, пробросов: {len(forwards)}")


def context(lan_cfg=None):
    """(wan, lan, wan_management, vpn, rules, forwards) или None, если LAN выключен."""
    from app.services import firewall_rules, lan, vpn   # здесь, чтобы не было циклического импорта
    cfg = lan_cfg or lan.get_config()
    wan_if = lan.wan_interface()
    if not (cfg.enabled and wan_if):
        return None
    return (wan_if, lan.BRIDGE, cfg.wan_management, vpn.firewall_rules(),
            firewall_rules.rules(), firewall_rules.forwards())


def refresh(lan_cfg=None) -> None:
    """Собрать правила из текущего состояния LAN, WAN, VPN и правил пользователя и применить.

    lan_cfg — новые настройки LAN, если они применяются прямо сейчас и ещё не сохранены.
    """
    from app.services import lan
    ctx = context(lan_cfg)
    if not ctx or not lan.load_state().get("address"):
        remove()   # фаервол работает вместе с LAN
        return
    apply(*ctx)


def remove() -> None:
    try:
        for t in LEGACY_TABLES:
            _nft(["delete", "table", "inet", t])
        _nft(["delete", "table", "inet", TABLE])
    except FirewallError:
        pass


def is_active() -> bool:
    try:
        return _nft(["list", "table", "inet", TABLE]).returncode == 0
    except FirewallError:
        return False


def counters() -> dict[str, tuple[int, int]]:
    """{'rule:3': (пакеты, байты), 'fwd:1': (...)} из живой таблицы."""
    try:
        r = _nft(["-j", "list", "table", "inet", TABLE])
    except FirewallError:
        return {}
    if r.returncode != 0:
        return {}
    out = {}
    try:
        for item in json.loads(r.stdout).get("nftables", []):
            rule = item.get("rule")
            if not rule or not rule.get("comment"):
                continue
            for expr in rule.get("expr", []):
                if "counter" in expr:
                    c = expr["counter"]
                    out[rule["comment"]] = (c.get("packets", 0), c.get("bytes", 0))
    except (ValueError, AttributeError):
        return {}
    return out
