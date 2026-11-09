# OutpostGate

**VPN-шлюз для удалённого сотрудника** на любом Linux с Docker: один WAN в интернет, LAN-порты для
телефона и компьютера, туннель в корпоративную сеть (WireGuard / AmneziaWG / L2TP).
Управление через **FastAPI**, веб-интерфейс и CLI в стиле **MikroTik RouterOS**;
конфиг как единый источник правды, Safe Mode, встроенные инструменты диагностики.

## Архитектура
- **Data plane** — ядро Linux хоста: маршрутизация, nftables, NAT.
- **Control plane** — Docker: FastAPI, веб-интерфейс, CLI по SSH, агент применения конфига.
- Работает на любом Linux с Docker (Debian, Ubuntu, Fedora, Armbian на NanoPi…): сеть делает ядро хоста.
  Внутри контейнера — Debian (python:3.12-slim).

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
- Веб-интерфейс: http://localhost:8000 — пользователь `admin`, пароль пустой (только из локальной сети)
- CLI в стиле MikroTik: `ssh -p 2222 admin@localhost` или `docker exec -it outpost-gate-dev outpost`
- Swagger: http://localhost:8000/docs

## CLI
```
[admin@office] > /ip address print
[admin@office] > /ip route
[admin@office] /ip route> add dst-address=10.0.0.0/8 gateway=192.168.88.254
[admin@office] /ip route> /ip dhcp-server lease make-static 3
[admin@office] > /ping 8.8.8.8 count=3
[admin@office] > /system shell        # bash; назад — exit или Ctrl-D
```
`?` — помощь в любом меню, Tab — подсказки, `ssh admin@router "/ip route print"` — одна команда.

## Дорожная карта
- [x] Каркас
- [x] Advanced: IP Addresses, IP Routes (двигатель)
- [x] WAN: DHCP-клиент / статика, автоопределение интерфейса
- [x] LAN: мост br-lan, dnsmasq (DHCP + DNS), закреплённые адреса, NAT, базовый фаервол
- [x] VPN → WireGuard: импорт .conf, full / split, kill switch, NAT или site-to-site
- [x] VPN → AmneziaWG (amneziawg-go, обфускация), L2TP/IPsec (strongSwan + xl2tpd)
- [x] Firewall: правила в стиле OCI Security Lists (входящие, транзит), проброс портов, счётчики, итоговый nftables
- [x] Tools: ping (IPv4/IPv6), сканер портов, traceroute, DNS, соседи (ARP), сканер сети (ping + ARP)
- [x] System: вход (admin без пароля при первом входе, как MikroTik), роли, пользователи, журнал, резервные копии и снимки, Safe Mode, ресурсы, перезапуск
- [x] Status: WAN, VPN, LAN, система, трафик интерфейсов
- [x] CLI в стиле MikroTik по SSH: меню, print с флагами и номерами, Tab, /system shell
- [ ] Дальше: VLAN, смена MAC, DHCP-опция 66, мониторинг (Prometheus), HTTPS
