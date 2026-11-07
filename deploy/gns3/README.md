# Запуск в GNS3 (Docker-узел)

Контейнер работает в собственном namespace — хост не затрагивается.
GNS3 сам создаёт интерфейсы eth0..ethN по числу адаптеров.

1. Собрать образ:
   ```bash
   docker build -t ubuntu-router:gns3 .
   ```
2. GNS3 → Edit → Preferences → Docker containers → New
   - Image: `ubuntu-router:gns3`
   - Adapters: 2 (eth0 = WAN, eth1 = LAN) или больше
   - Environment: `ROUTER_MODE=gns3`
   - Console type: telnet; HTTP-порт для веб-интерфейса: 8000
3. Перетащить узел на схему, соединить eth0 с NAT/облаком, eth1 — с клиентами.

## Сохранение конфига
Изменения из веб-интерфейса записываются в `/etc/ubuntu-router/router.yaml`.
Чтобы они переживали перезапуск узла, в настройках шаблона GNS3 укажите
**Persistent directories**:
```
/etc/ubuntu-router
/var/lib/ubuntu-router
```
