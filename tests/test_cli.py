"""
Тесты CLI в стиле MikroTik без сервера: API подменён записывающим фейком.
Проверяются: разбор путей и переходы по меню, вывод print, номера строк,
команды add/remove/enable, ошибки, автодополнение, Status.
"""
import pytest

from app.cli import commands as c
from app.cli.api import ApiError


class FakeApi:
    def __init__(self):
        self.calls = []
        self.data = {
            "/api/ip/addresses": [
                {"id": 1, "address": "192.168.88.1/24", "network": "192.168.88.0", "interface": "br-lan",
                 "comment": "LAN", "disabled": False, "invalid": False, "dynamic": False},
                {"id": None, "address": "172.18.0.2/16", "network": "172.18.0.0", "interface": "eth0",
                 "comment": None, "disabled": False, "invalid": False, "dynamic": True}],
            "/api/system/resource": {"identity": "office", "uptime": 90061, "version": "0.2.0", "mode": "dev",
                                     "model": "NanoPi R2S", "arch": "aarch64", "cpu_count": 4, "cpu_percent": 3.5,
                                     "memory": {"total": 1 << 30, "used": 1 << 28}, "disk": {"total": 8 << 30, "used": 2 << 30},
                                     "temperature": 48.0, "kernel": "6.1"},
            "/api/lan": {"config": {"enabled": True, "address": "192.168.88.1/24", "dhcp_enabled": True,
                                    "pool_start": "192.168.88.10", "pool_end": "192.168.88.254", "lease_time": "12h",
                                    "wan_management": True},
                         "active": True, "dns_dhcp_running": True, "ports": [],
                         "leases": [{"mac": "00:0b:82:aa:bb:cc", "ip": "192.168.88.20", "hostname": "GXP1625",
                                     "vendor": "Grandstream"}],
                         "static_leases": [{"mac": "aa:aa:aa:aa:aa:aa", "ip": "192.168.88.5", "name": "Принтер"}]},
            "/api/ip/routes": [
                {"id": 7, "dst_address": "10.0.0.0/8", "gateway": "192.168.88.254", "distance": 1, "interface": "br-lan",
                 "comment": None, "disabled": False, "dynamic": False, "active": True, "connected": False, "static": True}],
            "/api/tools/neighbors": [
                {"ip": "192.168.88.20", "mac": "00:0b:82:aa:bb:cc", "interface": "br-lan", "state": "REACHABLE",
                 "vendor": "Grandstream", "name": "GXP1625"}],
            "/api/tools/interfaces": {"interfaces": ["br-lan", "eth0", "eth1"], "scan_network": "192.168.88.0/24"},
            "/api/firewall": {"rules": [
                {"id": 1, "chain": "input", "enabled": True, "action": "accept", "in_zone": "wan", "out_zone": "any",
                 "src": "203.0.113.0/24", "dst": None, "protocol": "tcp", "src_ports": None, "dst_ports": "22",
                 "description": "SSH", "packets": 5, "bytes": 300},
                {"id": 2, "chain": "forward", "enabled": True, "action": "drop", "in_zone": "lan", "out_zone": "wan",
                 "src": "192.168.88.50/32", "dst": None, "protocol": "all", "src_ports": None, "dst_ports": None,
                 "description": None, "packets": 0, "bytes": 0},
                {"id": 3, "chain": "input", "enabled": True, "action": "accept", "in_zone": "vpn", "out_zone": "any",
                 "src": None, "dst": None, "protocol": "icmp", "src_ports": None, "dst_ports": None,
                 "description": "ping", "packets": 0, "bytes": 0}],
                "forwards": [{"id": 4, "enabled": True, "protocol": "tcp", "wan_port": "8080", "to_ip": "192.168.88.20",
                              "to_port": 80, "src": None, "description": "web", "packets": 1, "bytes": 60}],
                "system": {"input": ["LAN — всё"], "forward": ["LAN → WAN"], "nat": ["masquerade"]},
                "management_ports": [22, 8000]},
            "/api/system/users": [{"name": "admin", "role": "full", "must_change": False, "has_password": True},
                                  {"name": "ivan", "role": "read", "must_change": True, "has_password": True}],
            "/api/interfaces": [{"name": "eth0", "running": True, "mac": "02:00:00:00:00:01", "mtu": 1500,
                                 "addresses": ["10.0.0.45/24"], "rx_bytes": 1000, "tx_bytes": 500}],
            "/api/system/audit?limit=50": [{"time": "2026-11-10T20:00:00+02:00", "user": "admin", "method": "PUT",
                                            "path": "/api/wan", "status": 200, "ip": "10.0.0.5"}],
        }

    def get(self, path):
        self.calls.append(("GET", path, None))
        return self.data[path]

    def post(self, path, body=None):
        self.calls.append(("POST", path, body))
        if path.endswith("/move"):
            return {}
        if body and body.get("address") == "bad":
            raise ApiError("неверный адрес 'bad'")
        return {}

    def patch(self, path, body):
        self.calls.append(("PATCH", path, body))

    def delete(self, path):
        self.calls.append(("DELETE", path, None))

    def put(self, path, body):
        self.calls.append(("PUT", path, body))


@pytest.fixture
def ctx():
    out = []
    return c.Ctx(api=FakeApi(), out=out.append, confirm=lambda q: True), out


def test_navigation():
    assert c.execute(c.Ctx(api=None), "/ip address", []) == ["ip", "address"]
    assert c.execute(c.Ctx(api=None), "..", ["ip", "address"]) == ["ip"]
    assert c.execute(c.Ctx(api=None), "/", ["ip", "address"]) == []
    assert c.execute(c.Ctx(api=None), "route", ["ip"]) == ["ip", "route"]
    assert c.parse("/ip/address/print", [])[1].fn is c.address_print     # синтаксис RouterOS v7
    with pytest.raises(c.CliError, match="bad command name foo"):
        c.execute(c.Ctx(api=None), "/ip foo", [])


def test_print_and_numbers(ctx):
    cx, out = ctx
    c.execute(cx, "/ip address print", [])
    assert out[0] == "Flags: X - disabled, I - invalid, D - dynamic"
    assert out[1].split() == ["#", "ADDRESS", "NETWORK", "INTERFACE", "COMMENT"]
    assert out[2].split()[:2] == ["0", "192.168.88.1/24"] and out[3].split()[:2] == ["1", "D"]
    c.execute(cx, "disable 0", ["ip", "address"])                        # относительно текущего меню
    assert cx.api.calls[-1] == ("PATCH", "/api/ip/addresses/1", {"disabled": True})
    with pytest.raises(c.CliError, match="dynamic"):
        c.execute(cx, "remove 1", ["ip", "address"])
    with pytest.raises(c.CliError, match="no such item"):
        c.execute(cx, "remove 5", ["ip", "address"])


def test_add_and_errors(ctx):
    cx, _ = ctx
    c.execute(cx, '/ip address add address=10.0.0.1/24 interface=eth2 comment="test net"', [])
    assert cx.api.calls[-1] == ("POST", "/api/ip/addresses",
                                {"address": "10.0.0.1/24", "interface": "eth2", "comment": "test net", "disabled": False})
    with pytest.raises(c.CliError, match="missing value.*interface"):
        c.execute(cx, "/ip address add address=10.0.0.1/24", [])
    with pytest.raises(c.CliError, match="failure: неверный адрес"):
        c.execute(cx, "/ip address add address=bad interface=eth0", [])
    with pytest.raises(c.CliError, match="сначала выполните print"):
        c.execute(c.Ctx(api=FakeApi()), "/ip route remove 0", [])


def test_leases_make_static(ctx):
    cx, out = ctx
    c.execute(cx, "/ip dhcp-server lease print", [])
    assert out[2].split()[:3] == ["0", "S", "192.168.88.5"]              # закреплённые — первыми
    c.execute(cx, "/ip dhcp-server lease make-static 1", [])
    assert cx.api.calls[-1] == ("POST", "/api/lan/static-leases",
                                {"mac": "00:0b:82:aa:bb:cc", "ip": "192.168.88.20", "name": "GXP1625"})
    with pytest.raises(c.CliError, match="только закреплённую"):
        c.execute(cx, "/ip dhcp-server lease remove 1", [])


def test_system_resource_and_identity(ctx):
    cx, out = ctx
    c.execute(cx, "/system resource print", [])
    text = "\n".join(out)
    assert "uptime: 1d1h1m1s" in text and "board-name: NanoPi R2S" in text and "cpu-load: 3.5%" in text
    c.execute(cx, "/system identity set name=Офис", [])
    assert cx.api.calls[-1] == ("PUT", "/api/system/identity", {"identity": "Офис"})


def test_shell_and_permissions(ctx):
    cx, _ = ctx
    opened = []
    cx.shell = lambda: opened.append(True)
    c.execute(cx, "/system shell", [])
    assert opened
    with pytest.raises(c.CliError, match="permissions"):
        c.execute(c.Ctx(api=FakeApi(), role="read", shell=lambda: None), "/system shell", [])
    with pytest.raises(c.Quit):
        c.execute(cx, "quit", [])
    with pytest.raises(c.Quit):
        c.execute(cx, "quit", ["ip", "route"])                       # глобальные команды — из любого меню


def test_ping_validation(ctx):
    cx, _ = ctx
    for bad in ("/ping", "/ping -c1", "/ping 8.8.8.8;rm"):
        with pytest.raises(c.CliError):
            c.execute(cx, bad, [])


def test_completion():
    assert c.complete("", []) == sorted(c.ROOT.children)
    assert c.complete("/ip a", []) == ["address", "arp"]
    assert c.complete("/ip ", []) == ["address", "arp", "dhcp-client", "dhcp-server", "dns", "firewall",
                                      "neighbor", "pool", "route", "service"]
    assert c.complete("/ip/ad", []) == ["/ip/address"]
    assert c.complete("add ", ["ip", "address"]) == ["address=", "interface=", "comment=", "disabled="]
    assert c.complete("add disabled=", ["ip", "address"]) == ["disabled=yes", "disabled=no"]
    assert c.complete("print ", ["ip", "route"]) == ["detail"]
    assert c.complete("add address=1.1.1.1/32 i", ["ip", "address"]) == ["interface="]
    assert c.complete("pr", ["ip", "route"]) == ["print"]
    assert c.complete("/nothing ", []) == []


def test_help(ctx):
    cx, out = ctx
    c.execute(cx, "?", ["ip"])
    assert out[0].startswith("/ip") and any("/address" in line for line in out)


def test_status_overview_survives_errors(monkeypatch):
    from app.services import status
    monkeypatch.setattr(status, "_system", lambda: {"identity": "x"})
    monkeypatch.setattr(status, "_wan", lambda: (_ for _ in ()).throw(RuntimeError("нет netlink")))
    for name in ("_lan", "_vpn", "_firewall", "_traffic"):
        monkeypatch.setattr(status, name, lambda: {})
    o = status.overview()
    assert o["system"] == {"identity": "x"} and o["wan"] == {"error": "нет netlink"} and "time" in o


def test_abbreviations(ctx):
    cx, out = ctx
    c.execute(cx, "/ip addr pr", [])
    assert out[1].split()[1] == "ADDRESS"
    c.execute(cx, "/ip addr add addr=10.0.0.1/24 int=eth2", [])                 # сокращённые параметры
    assert cx.api.calls[-1][2]["interface"] == "eth2"
    with pytest.raises(c.CliError, match="ambiguous value of a"):
        c.execute(cx, "/ip a print", [])                                       # address или arp
    with pytest.raises(c.CliError, match="unknown parameter"):
        c.execute(cx, "/ip address add zzz=1", [])


def test_print_detail_and_set(ctx):
    cx, out = ctx
    c.execute(cx, "/ip route print detail", [])
    assert out[1].startswith("0 AS dst-address=10.0.0.0/8 gateway=192.168.88.254")
    c.execute(cx, '/ip route set 0 distance=5 comment="backup link"', [])
    assert cx.api.calls[-1] == ("PATCH", "/api/ip/routes/7", {"distance": 5, "comment": "backup link"})
    c.execute(cx, "/ip address print", [])
    c.execute(cx, '/ip address comment 0 comment=LAN-main', [])
    assert cx.api.calls[-1] == ("PATCH", "/api/ip/addresses/1", {"comment": "LAN-main"})
    with pytest.raises(c.CliError, match="dynamic"):
        c.execute(cx, "/ip address set 1 comment=x", [])


def test_arp_and_value_completion(ctx):
    cx, out = ctx
    c.execute(cx, "/ip arp print", [])
    assert "GXP1625" in out[2] and "reachable" in out[2]
    assert c.complete("/ping 8.8.8.8 interface=e", [], cx) == ["interface=eth0", "interface=eth1"]
    assert c.complete("/ip firewall filter add chain=", [], cx) == ["chain=input", "chain=forward"]


def test_firewall_cli(ctx):
    cx, out = ctx
    c.execute(cx, "/ip firewall filter add chain=input protocol=tcp dst-port=443 in-interface-list=WAN "
                  "src-address=198.51.100.0/24 comment=HTTPS", [])
    assert cx.api.calls[-1] == ("POST", "/api/firewall/rules", {
        "chain": "input", "enabled": True, "action": "accept", "in_zone": "wan", "out_zone": "any",
        "protocol": "tcp", "src": "198.51.100.0/24", "dst_ports": "443", "description": "HTTPS"})
    with pytest.raises(c.CliError, match="порты"):
        c.execute(cx, "/ip firewall filter add chain=input dst-port=22", [])
    c.execute(cx, "/ip firewall filter print", [])
    c.execute(cx, "/ip firewall filter disable 0", [])
    assert cx.api.calls[-1][0:2] == ("PUT", "/api/firewall/rules/1") and cx.api.calls[-1][2]["enabled"] is False
    c.execute(cx, "/ip firewall filter move 2 0", [])                          # input: правило 3 -> на место 1
    assert cx.api.calls[-1] == ("POST", "/api/firewall/rules/3/move", {"direction": "up"})
    with pytest.raises(c.CliError, match="цепочки"):
        c.execute(cx, "/ip firewall filter move 1 0", [])                      # forward -> input нельзя


def test_nat_cli(ctx):
    cx, _ = ctx
    c.execute(cx, "/ip firewall nat add chain=dstnat action=dst-nat protocol=tcp dst-port=5060 "
                  "to-addresses=192.168.88.21", [])
    assert cx.api.calls[-1] == ("POST", "/api/firewall/forwards",
                                {"enabled": True, "protocol": "tcp", "wan_port": "5060", "to_ip": "192.168.88.21"})
    with pytest.raises(c.CliError, match="srcnat"):
        c.execute(cx, "/ip firewall nat add chain=srcnat action=masquerade dst-port=1 to-addresses=1.1.1.1", [])
    c.execute(cx, "/ip firewall nat print", [])
    c.execute(cx, "/ip firewall nat set 0 to-ports=8081", [])
    assert cx.api.calls[-1][2]["to_port"] == 8081 and cx.api.calls[-1][2]["wan_port"] == "8080"


def test_users_password_log(ctx):
    cx, out = ctx
    cx.secret = lambda prompt: "Secret123"
    c.execute(cx, "/user add name=petr group=read", [])
    assert cx.api.calls[-1] == ("POST", "/api/system/users", {"name": "petr", "password": "Secret123", "role": "read"})
    c.execute(cx, "/user print", [])
    assert "сменит при входе" in out[-1]
    c.execute(cx, "/user remove 1", [])
    assert cx.api.calls[-1] == ("DELETE", "/api/system/users/ivan", None)
    c.execute(cx, "password", ["ip"])                                          # из любого меню
    assert cx.api.calls[-1] == ("POST", "/api/auth/password", {"old": "Secret123", "new": "Secret123"})
    answers = iter(["old", "new-1", "new-2"])
    cx.secret = lambda prompt: next(answers)
    with pytest.raises(c.CliError, match="не совпадают"):
        c.execute(cx, "/password", [])
    c.execute(cx, "/log print", [])
    assert "admin" in out[-1] and "/api/wan" in out[-1]


def test_monitor_traffic_once(ctx):
    cx, out = ctx
    calls = iter([1000, 126000])
    def get(path):
        if path == "/api/interfaces":
            rx = next(calls)
            return [{"name": "eth0", "rx_bytes": rx, "tx_bytes": rx // 2}]
        return FakeApi().get(path)
    cx.api.get = get
    cx.sleep = lambda s: None
    c.execute(cx, "/interface monitor-traffic eth0 once=yes", [])
    assert "rx-bits-per-second" in out[-1]


def test_help_for_command(ctx):
    cx, out = ctx
    c.execute(cx, "/ip address add ?", [])
    assert out[0].startswith("добавить") and "interface=" in out[1]


def test_nat_from_vpn(ctx):
    cx, out = ctx
    c.execute(cx, "/ip firewall nat add chain=dstnat action=dst-nat protocol=udp dst-port=5060 "
                  "to-addresses=192.168.1.50 in-interface-list=VPN", [])
    post = [x for x in cx.api.calls if x[0] == "POST"][-1]
    assert post[2]["from_zone"] == "vpn" and post[2]["wan_port"] == "5060"
    with pytest.raises(c.CliError, match="in-interface-list"):
        c.execute(cx, "/ip firewall nat add dst-port=1 to-addresses=192.168.1.5 in-interface-list=LAN", [])


def test_resolve_and_without_paging(ctx, monkeypatch):
    from app.services import tools
    cx, out = ctx
    monkeypatch.setattr(tools, "resolve_sync", lambda h, f=None: ("192.168.88.30", "DNS роутера: nas.lan"))
    c.execute(cx, ":resolve nas", [])
    assert out[-1] == "192.168.88.30"
    c.execute(cx, "/ip firewall nat print without-paging", [])         # так спрашивает Ansible (community.routeros)
