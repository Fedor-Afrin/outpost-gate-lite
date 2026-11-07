# Ubuntu Router

Роутер на Ubuntu с управлением через **FastAPI** и веб-интерфейсом.
Идеология — **MikroTik RouterOS**: разделы Interfaces / IP / Firewall / Tools / System,
конфиг как единый источник правды, Safe Mode.

## Архитектура
- **Data plane** — ядро Linux хоста: маршрутизация, nftables, NAT.
- **Control plane** — Docker: FastAPI, веб-интерфейс, агент применения конфига.

## Режимы запуска (один образ)
| Режим | Где | Сеть | Файл |
|-------|-----|------|------|
| dev   | рабочий ПК | свой namespace, хост не трогается | `docker-compose.yml` |
| gns3  | GNS3 Docker-узел | свой namespace, eth0..N от GNS3 | `deploy/gns3/` |
| host  | VM / сервер / железо | сеть сервера (`network_mode: host`) | `deploy/host/` |

## Быстрый старт (dev)
```bash
docker compose up --build
```
- Веб-интерфейс: http://localhost:8000
- Swagger: http://localhost:8000/docs

## Дорожная карта
- [x] Каркас, список интерфейсов
- [ ] IP-адреса, маршруты
- [ ] Firewall + NAT (nftables)
- [ ] DHCP-сервер
- [ ] Safe Mode, export/import конфига
- [ ] VLAN, Bridge, WireGuard, мониторинг трафика
