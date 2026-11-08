"""
Агент применения конфигурации.

router.yaml — единый источник правды (аналог /export в RouterOS).
При старте контейнера агент приводит систему к конфигу:
  - ip_forward                       готово
  - адреса на интерфейсах            готово (этап 1)
  - маршруты                         готово (этап 1)
  - DHCP-клиент / сервер, DNS        этап 1 (dnsmasq)
  - nftables: filter + NAT           этап 2 (nft -f, атомарно)
  - Safe Mode                        этап System
"""
from app.services import addresses, routes, sysctl


def apply_startup() -> None:
    if sysctl.set_ip_forward(True):
        print("[agent] ip_forward = 1")
    else:
        print("[agent] WARNING: не удалось включить ip_forward "
              "(нужен NET_ADMIN / --sysctl net.ipv4.ip_forward=1)")

    try:
        addresses.apply_all()
    except Exception as e:  # агент не должен мешать запуску API
        print(f"[agent] ERROR: применение адресов: {e}")

    try:  # маршруты — строго после адресов: шлюз должен быть в подключённой сети
        routes.apply_all()
    except Exception as e:
        print(f"[agent] ERROR: применение маршрутов: {e}")


if __name__ == "__main__":
    apply_startup()
