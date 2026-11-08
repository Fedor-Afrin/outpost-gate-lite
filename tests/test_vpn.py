"""
Тесты VPN → WireGuard без ядра и без утилиты wg: всё системное подменяется.
WAN = eth1 (шлюз 172.18.0.1), LAN включён на br-lan 192.168.88.1/24.
"""
import pytest
import yaml

from app.core.store import ConfigStore
from app.models.wireguard import WgConfig, parse_wg_quick
from app.services import firewall, lan, netlink, vpn, wan

PRIV = "yAnz5TF+lXXJte14tji3zlMNq+hd2rYUIgJBgB3fBmk="
PUB = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="

CONF = f"""
[Interface]
PrivateKey = {PRIV}
Address = 10.8.0.2/32, fd00::2/128
DNS = 10.8.0.1
MTU = 1380
Jc = 4            # параметры AmneziaWG пока игнорируются

[Peer]
PublicKey = {PUB}
Endpoint = 203.0.113.7:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


class FakeKernel:
    def __init__(self):
        self.links = {"lo", "eth0", "eth1", "br-lan"}
        self.addrs = set()
        self.routes = [{"dst": "0.0.0.0/0", "gateway": "172.18.0.1", "interface": "eth1", "metric": 0, "proto": 3}]
        self.mtu = {}

    def link_names(self): return set(self.links)
    def link_set_up(self, n): assert n in self.links
    def link_set_mtu(self, n, m): self.mtu[n] = m
    def wireguard_create(self, n): self.links.add(n)
    def link_delete(self, n):
        self.links.discard(n)
        self.addrs = {(i, a) for i, a in self.addrs if i != n}
        self.routes = [r for r in self.routes if r["interface"] != n]
    def kernel_ipv4_routes(self): return [dict(r) for r in self.routes]
    def addr_add(self, n, c): self.addrs.add((n, c))
    def route_add(self, dst, gateway=None, ifname=None, metric=1, proto=4):
        self.routes.append({"dst": dst, "gateway": gateway, "interface": ifname or "eth1",
                            "metric": metric, "proto": proto})
    def route_del(self, dst, gateway=None, ifname=None, metric=1):
        self.routes = [r for r in self.routes if not (r["dst"] == dst and r["gateway"] == gateway)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "router.yaml"
    cfg.write_text(yaml.safe_dump({
        "wan": {"interface": "eth1", "mode": "none"},
        "lan": {"enabled": True, "address": "192.168.88.1/24"},
    }))
    store = ConfigStore(str(cfg), str(tmp_path / "data"))
    (tmp_path / "data").mkdir()
    kernel = FakeKernel()
    for mod in (vpn, lan, wan):
        monkeypatch.setattr(mod, "store", store)
    monkeypatch.setattr(vpn, "_data", lambda name: tmp_path / "data" / name)
    monkeypatch.setattr(lan, "_data", lambda name: tmp_path / "data" / name)
    monkeypatch.setattr(wan, "state_file", lambda: tmp_path / "data" / "wan.json")
    monkeypatch.setattr(wan, "resolv_file", lambda: tmp_path / "data" / "resolv.wan")
    monkeypatch.setattr(wan, "system_nameservers", lambda: ["127.0.0.11"])
    for name in ("link_names", "link_set_up", "link_set_mtu", "wireguard_create", "link_delete",
                 "kernel_ipv4_routes", "addr_add", "route_add", "route_del"):
        monkeypatch.setattr(netlink, name, getattr(kernel, name))
    wg_calls = []
    def fake_wg(*args, stdin=None):
        wg_calls.append(args)
        return PUB if args[0] == "pubkey" else ""
    monkeypatch.setattr(vpn, "_wg", fake_wg)
    fw = []
    monkeypatch.setattr(firewall, "refresh", lambda lan_cfg=None: fw.append(vpn.firewall_rules()))
    return store, kernel, wg_calls, fw


def _routes(kernel, iface):
    return sorted(r["dst"] for r in kernel.routes if r["interface"] == iface)


def test_parse_wg_quick():
    c = parse_wg_quick(CONF)
    assert c.private_key == PRIV and c.peer_public_key == PUB
    assert c.addresses == ["10.8.0.2/32"]          # IPv6 пропущен
    assert c.dns == ["10.8.0.1"] and c.mtu == 1380
    assert c.mode == "full" and c.allowed_ips == ["0.0.0.0/0"]
    split = parse_wg_quick(CONF.replace("0.0.0.0/0, ::/0", "10.0.0.0/8, 192.168.10.0/24"))
    assert split.mode == "split" and split.split_networks() == ["10.0.0.0/8", "192.168.10.0/24"]
    with pytest.raises(ValueError):
        parse_wg_quick("[Interface]\nPrivateKey = x")


def test_full_mode(env):
    store, kernel, wg_calls, fw = env
    cfg = parse_wg_quick(CONF).model_copy(update={"enabled": True})
    st = vpn.update(cfg)
    assert ("wg0", "10.8.0.2/32") in kernel.addrs and kernel.mtu["wg0"] == 1380
    assert _routes(kernel, "wg0") == ["0.0.0.0/1", "128.0.0.0/1"]
    ep = [r for r in kernel.routes if r["dst"] == "203.0.113.7/32"]
    assert ep and ep[0]["gateway"] == "172.18.0.1"                  # до сервера — через WAN
    assert ("setconf", "wg0", str(vpn._data("wg0.conf"))) in wg_calls
    conf = vpn._data("wg0.conf").read_text()
    assert "AllowedIPs = 0.0.0.0/0" in conf and "Endpoint = 203.0.113.7:51820" in conf
    rules = fw[-1]
    assert rules.killswitch and rules.nat and not rules.inbound
    assert "nameserver 10.8.0.1" in wan.resolv_file().read_text()   # DNS не утекает мимо туннеля
    assert st.public_key == PUB and st.config.private_key is None   # ключ наружу не отдаётся
    assert store.load()["vpn"]["wireguard"]["private-key"] == PRIV


def test_split_site_to_site(env):
    _, kernel, _, fw = env
    cfg = parse_wg_quick(CONF.replace("0.0.0.0/0, ::/0", "10.0.0.0/8, 192.168.10.0/24"))
    vpn.update(cfg.model_copy(update={"enabled": True, "nat": False}))
    assert _routes(kernel, "wg0") == ["10.0.0.0/8", "192.168.10.0/24"]
    rules = fw[-1]
    assert not rules.killswitch and not rules.nat and rules.inbound   # центр видит устройства LAN
    assert "nameserver 10.8.0.1" not in wan.resolv_file().read_text() # DNS туннеля только в full
    assert "AllowedIPs = 10.0.0.0/8, 192.168.10.0/24" in vpn._data("wg0.conf").read_text()


def test_disable_cleans_up(env):
    _, kernel, _, fw = env
    vpn.update(parse_wg_quick(CONF).model_copy(update={"enabled": True}))
    vpn.update(vpn.get_config().model_copy(update={"enabled": False, "private_key": None}))
    assert "wg0" not in kernel.links
    assert not [r for r in kernel.routes if r["dst"] == "203.0.113.7/32"]
    assert fw[-1] is None                                           # kill switch снят
    assert vpn.get_config().private_key == PRIV                     # пустой ключ = прежний


def test_lan_overlap_rejected_and_rolled_back(env):
    store, kernel, _, _ = env
    bad = parse_wg_quick(CONF.replace("0.0.0.0/0, ::/0", "192.168.88.0/24"))
    with pytest.raises(vpn.VpnError, match="пересекается"):
        vpn.update(bad.model_copy(update={"enabled": True}))
    assert "wg0" not in kernel.links
    assert not vpn.get_config().enabled


def test_endpoint_route_follows_wan_gateway(env):
    _, kernel, _, _ = env
    vpn.update(parse_wg_quick(CONF).model_copy(update={"enabled": True}))
    kernel.routes[0]["gateway"] = "172.18.0.254"                    # новая аренда DHCP
    vpn.refresh_endpoint_route()
    ep = [r for r in kernel.routes if r["dst"] == "203.0.113.7/32"]
    assert len(ep) == 1 and ep[0]["gateway"] == "172.18.0.254"


def test_validation():
    with pytest.raises(ValueError, match="не хватает"):
        WgConfig(enabled=True, addresses=["10.8.0.2/32"])
    with pytest.raises(ValueError, match="ключ"):
        WgConfig(peer_public_key="short")
    with pytest.raises(ValueError, match="Endpoint"):
        WgConfig(endpoint="vpn.example.com")
    with pytest.raises(ValueError, match="split"):
        WgConfig(enabled=True, addresses=["10.8.0.2/32"], peer_public_key=PUB,
                 endpoint="1.2.3.4:51820", mode="split", allowed_ips=["0.0.0.0/0"])


def test_firewall_with_killswitch_has_no_lan_to_wan():
    rs = firewall.ruleset("eth1", "br-lan", True, firewall.VpnRules("wg0", True, True, False))
    assert 'iifname "br-lan" oifname "eth1" accept' not in rs
    assert 'iifname "br-lan" oifname "wg0" accept' in rs and 'oifname "wg0" masquerade' in rs
    assert "maxseg size set rt mtu" in rs
