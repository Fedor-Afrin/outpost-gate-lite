# OutpostGate Lite

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
- CLI в стиле MikroTik: `ssh -p 2222 admin@localhost` или `docker exec -it outpost-gate-lite-dev outpost`
- Swagger: http://localhost:8000/docs

## Языки интерфейса
English (по умолчанию), Русский, עברית — переключатель внизу левого меню и на странице входа, без перезагрузки.
Выбор запоминается в браузере; для иврита страница переходит в режим справа налево.
Словарь — `web/js/i18n-dict.js` (ключ — русская фраза, значение — `[English, иврит]`);
`tests/test_i18n.py` проверяет, что каждая фраза `index.html` в нём есть.

## CLI
Синтаксис MikroTik RouterOS, включая сокращения (`/ip addr pr`), `print detail`, номера строк из `print`.
```
[admin@office] > /ip address print
[admin@office] > /ip route
[admin@office] /ip route> add dst-address=10.0.0.0/8 gateway=192.168.88.254
[admin@office] /ip route> set 0 distance=5 comment="резерв"
[admin@office] > /ip arp print
[admin@office] > /ip dhcp-server lease make-static 3
[admin@office] > /ip firewall filter add chain=input protocol=tcp dst-port=22 in-interface-list=WAN src-address=203.0.113.0/24
[admin@office] > /ip firewall nat add chain=dstnat action=dst-nat protocol=tcp dst-port=8080 to-addresses=192.168.88.20 to-ports=80
[admin@office] > /interface monitor-traffic eth0
[admin@office] > /tool ip-scan address-range=192.168.88.0/24
[admin@office] > /user add name=ivan group=read
[admin@office] > /system shell        # bash; назад — exit или Ctrl-D
```
Меню: `/interface` (ethernet, bridge, wireguard, l2tp-client, monitor-traffic), `/ip` (address, route, arp,
neighbor, pool, dhcp-server, dhcp-client, dns, service, firewall filter/nat), `/wan`, `/lan`, `/vpn`, `/system`
(resource, identity, clock, routerboard, package, shell, reboot), `/user`, `/password`, `/log`, `/tool`
(ping, traceroute, ip-scan, dns-lookup), `/export`.
`?` — помощь в меню, `команда ?` — параметры команды, Tab — подсказки (и значения: интерфейсы, chain=, action=).
Одна команда без входа: `ssh admin@router "/ip route print"`.

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
- [x] CLI в стиле MikroTik по SSH: ~70 команд, сокращения, print detail, set/move, Tab со значениями, /system shell
- [x] Веб-интерфейс без раздела Advanced: адреса и маршруты — в CLI
- [ ] Дальше: VLAN, смена MAC, DHCP-опция 66, мониторинг (Prometheus), HTTPS
