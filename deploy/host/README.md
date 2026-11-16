# Развёртывание на сервере / VM

Проще всего — установщиком из корня проекта:

```bash
sudo ./install.sh              # мастер: порты WAN / LAN, адрес LAN, пароль admin
sudo ./install.sh --update     # после update_*.sh: пересобрать образ и перезапустить
sudo ./install.sh --status
sudo ./install.sh --uninstall  # настройки остаются; с --purge — удалить и их
./install.sh --help            # установка без вопросов (для Ansible и т. п.)
```

Что он делает:
- ставит Docker и запрещает ему трогать фаервол (`daemon.json: iptables=false`) — иначе Docker
  ставит `FORWARD DROP` и транзит роутера перестаёт ходить; уже стоящий `FORWARD DROP` снимает;
- убирает порты роутера из-под netplan/systemd-networkd и NetworkManager
  (порт, через который вы подключены по SSH, без вашего согласия не трогается);
- включает `ip_forward`, модули ядра для WireGuard и L2TP (и в автозагрузку);
- даёт самому серверу свои DNS (порт WAN забирает роутер — без этого образ не соберётся при обновлении);
- собирает образ в сети сервера (`docker build --network host`), пишет первый router.yaml и запускает.

Веб-интерфейс — на порту 80 (`http://<адрес LAN>`); если порт 80 на сервере занят — на 8000.
Сменить потом: `sudo ./install.sh --update --api-port 8080`.

Вручную (без установщика):
```bash
sudo cp daemon.json.example /etc/docker/daemon.json
sudo systemctl restart docker
sudo mkdir -p /etc/outpost-gate-lite /var/lib/outpost-gate-lite
sudo cp ../../config/router.yaml /etc/outpost-gate-lite/
docker compose up -d --build
```
и отключите netplan и NetworkManager на управляемых интерфейсах, чтобы они не перетирали настройки роутера.

## Переход со старых названий (ubuntu-router или outpost-gate -> outpost-gate-lite)

Если роутер уже работал под старым названием, перенесите настройки один раз:
```bash
docker compose -p ubuntu-router down 2>/dev/null || true
# было outpost-gate:
sudo mv /etc/outpost-gate /etc/outpost-gate-lite
sudo mv /var/lib/outpost-gate /var/lib/outpost-gate-lite
# или было ubuntu-router:
# sudo mv /etc/ubuntu-router /etc/outpost-gate-lite && sudo mv /var/lib/ubuntu-router /var/lib/outpost-gate-lite
docker compose up -d --build
```
Старые таблицы фаервола (`inet ubuntu_router`, `inet outpost_gate`) удаляются автоматически.

## Командная строка (CLI)
`ssh -p 2222 admin@<адрес роутера>` — оболочка в стиле MikroTik. Порт 22 остаётся SSH самого сервера.
