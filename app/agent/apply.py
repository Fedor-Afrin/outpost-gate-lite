"""
Агент применения конфигурации.

router.yaml — единый источник правды (аналог /export в RouterOS).
При старте API агент приводит систему к конфигу, строго по порядку:
  1. ip_forward
  2. WAN (адрес/шлюз или запуск DHCP-клиента)
  3. адреса из Advanced → IP Addresses
  4. маршруты из Advanced → IP Routes  (после адресов: шлюз должен быть доступен)
Дальше: LAN (мост + dnsmasq), VPN, nftables, Safe Mode.
"""
from app.services import addresses, routes, sysctl, wan


def _step(name: str, fn) -> None:
    try:
        fn()
    except Exception as e:  # агент не должен мешать запуску API
        print(f"[agent] ERROR: {name}: {e}")


def apply_startup() -> None:
    if sysctl.set_ip_forward(True):
        print("[agent] ip_forward = 1")
    else:
        print("[agent] WARNING: не удалось включить ip_forward "
              "(нужен NET_ADMIN / --sysctl net.ipv4.ip_forward=1)")

    _step("WAN", wan.apply_startup)
    _step("адреса", addresses.apply_all)
    _step("маршруты", routes.apply_all)
