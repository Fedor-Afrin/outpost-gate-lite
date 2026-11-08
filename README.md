# Ubuntu Router

**VPN-шлюз для удалённого сотрудника** на Ubuntu: один WAN в интернет, LAN-порты для
телефона и компьютера, туннель в корпоративную сеть (WireGuard / AmneziaWG / L2TP).
Управление через **FastAPI**, веб-интерфейс и CLI в стиле **MikroTik RouterOS**;
конфиг как единый источник правды, Safe Mode, встроенные инструменты диагностики.

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
- [x] Каркас
- [x] Advanced: IP Addresses, IP Routes (двигатель)
- [x] WAN: DHCP-клиент / статика, автоопределение интерфейса
- [x] LAN: мост br-lan, dnsmasq (DHCP + DNS), NAT, базовый фаервол
- [ ] VPN: WireGuard, AmneziaWG, L2TP/IPsec
- [ ] Status, Firewall, Tools, System, CLI
