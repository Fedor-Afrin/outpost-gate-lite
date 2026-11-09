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
        }

    def get(self, path):
        self.calls.append(("GET", path, None))
        return self.data[path]

    def post(self, path, body=None):
        self.calls.append(("POST", path, body))
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
    assert c.complete("/ip a", []) == ["address"]
    assert c.complete("/ip ", []) == ["address", "dhcp-server", "dns", "firewall", "route"]
    assert c.complete("/ip/ad", []) == ["/ip/address"]
    assert c.complete("add ", ["ip", "address"]) == ["address=", "interface=", "comment=", "disabled="]
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
