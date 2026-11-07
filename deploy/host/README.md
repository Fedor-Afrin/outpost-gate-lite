# Развёртывание на сервере / VM

Docker по умолчанию ставит политику `FORWARD` в `DROP` — транзитный трафик
роутера перестанет ходить. Поэтому Docker'у запрещаем трогать фаервол:

```bash
sudo cp daemon.json.example /etc/docker/daemon.json
sudo systemctl restart docker

sudo mkdir -p /etc/ubuntu-router /var/lib/ubuntu-router
sudo cp ../../config/router.yaml /etc/ubuntu-router/

docker compose up -d --build
```

Также отключите/ограничьте netplan и NetworkManager на управляемых интерфейсах,
чтобы они не перетирали настройки роутера.
