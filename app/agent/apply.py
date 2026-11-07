"""
Агент применения конфигурации (заготовка).

Идея: router.yaml — единый источник правды (аналог /export в RouterOS).
Агент читает конфиг и приводит систему к нему:
  - ip_forward
  - адреса на интерфейсах   (этап 1)
  - маршруты                (этап 1)
  - nftables: filter + NAT  (этап 1, применение атомарно: nft -f)
  - DHCP-сервер             (этап 1)
  - Safe Mode: откат, если изменение не подтверждено за N секунд
"""
from app.services import sysctl


def apply_startup() -> None:
    """Вызывается при старте контейнера."""
    if sysctl.set_ip_forward(True):
        print("[agent] ip_forward = 1")
    else:
        print("[agent] WARNING: не удалось включить ip_forward "
              "(нужен NET_ADMIN / --sysctl net.ipv4.ip_forward=1)")


if __name__ == "__main__":
    apply_startup()
