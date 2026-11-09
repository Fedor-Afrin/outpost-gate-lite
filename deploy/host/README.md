# Развёртывание на сервере / VM

Docker по умолчанию ставит политику `FORWARD` в `DROP` — транзитный трафик
роутера перестанет ходить. Поэтому Docker'у запрещаем трогать фаервол:

```bash
sudo cp daemon.json.example /etc/docker/daemon.json
sudo systemctl restart docker

sudo mkdir -p /etc/outpost-gate /var/lib/outpost-gate
sudo cp ../../config/router.yaml /etc/outpost-gate/

docker compose up -d --build
```

Также отключите/ограничьте netplan и NetworkManager на управляемых интерфейсах,
чтобы они не перетирали настройки роутера.

## Переход со старого названия (ubuntu-router -> outpost-gate)

Если роутер уже работал под старым названием, перенесите настройки один раз:
```bash
docker compose -p ubuntu-router down 2>/dev/null || true
sudo mv /etc/ubuntu-router /etc/outpost-gate
sudo mv /var/lib/ubuntu-router /var/lib/outpost-gate
docker compose up -d --build
```
Старая таблица фаервола `inet ubuntu_router` удаляется автоматически.

## Командная строка (CLI)
`ssh -p 2222 admin@<адрес роутера>` — оболочка в стиле MikroTik. Порт 22 остаётся SSH самого сервера.
