"""
Низкоуровневые операции с ядром через netlink (pyroute2).

Единственное место, где код трогает сеть системы. Всё остальное
(API, CLI, агент) работает через сервисы, которые вызывают эти функции.
"""
from __future__ import annotations

import errno
import ipaddress


class NetlinkOpError(Exception):
    pass


def _ipr():
    from pyroute2 import IPRoute  # импорт здесь — чтобы тесты работали без pyroute2
    return IPRoute()


def link_names() -> set[str]:
    with _ipr() as ipr:
        return {l.get_attr("IFLA_IFNAME") for l in ipr.get_links()}


def _index(ipr, ifname: str) -> int:
    idx = ipr.link_lookup(ifname=ifname)
    if not idx:
        raise NetlinkOpError(f"интерфейс {ifname} не найден")
    return idx[0]


def kernel_ipv4_addresses() -> list[tuple[str, str]]:
    """[(ifname, '192.168.88.1/24'), ...] — IPv4-адреса, реально назначенные в ядре."""
    with _ipr() as ipr:
        names = {l["index"]: l.get_attr("IFLA_IFNAME") for l in ipr.get_links()}
        out = []
        for a in ipr.get_addr(family=2):  # AF_INET
            ip = a.get_attr("IFA_ADDRESS")
            if ip:
                out.append((names.get(a["index"], str(a["index"])), f"{ip}/{a['prefixlen']}"))
        return out


def addr_add(ifname: str, cidr: str) -> None:
    from pyroute2 import NetlinkError
    iface = ipaddress.ip_interface(cidr)
    kwargs = {"address": str(iface.ip), "prefixlen": iface.network.prefixlen}
    if iface.version == 4 and iface.network.prefixlen <= 30:
        kwargs["broadcast"] = str(iface.network.broadcast_address)  # как делает RouterOS
    with _ipr() as ipr:
        try:
            ipr.addr("add", index=_index(ipr, ifname), **kwargs)
        except NetlinkError as e:
            if e.code != errno.EEXIST:  # уже есть — это нормально
                raise NetlinkOpError(f"не удалось добавить {cidr} на {ifname}: {e}") from e


def addr_del(ifname: str, cidr: str) -> None:
    from pyroute2 import NetlinkError
    iface = ipaddress.ip_interface(cidr)
    with _ipr() as ipr:
        try:
            idx = _index(ipr, ifname)
        except NetlinkOpError:
            return  # интерфейса нет — удалять нечего
        try:
            ipr.addr("del", index=idx, address=str(iface.ip), prefixlen=iface.network.prefixlen)
        except NetlinkError as e:
            if e.code not in (errno.EADDRNOTAVAIL, errno.ENODEV):
                raise NetlinkOpError(f"не удалось удалить {cidr} с {ifname}: {e}") from e
