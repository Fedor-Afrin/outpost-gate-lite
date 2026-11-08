#!/bin/sh
set -e
echo "[entrypoint] Ubuntu Router, mode=${ROUTER_MODE}"

# Устройства для VPN: /dev/net/tun (AmneziaWG) и /dev/ppp (L2TP).
# Docker разрешает tun по умолчанию; ppp — через device_cgroup_rules в compose.
mkdir -p /dev/net
[ -e /dev/net/tun ] || mknod /dev/net/tun c 10 200 2>/dev/null || echo "[entrypoint] нет /dev/net/tun — AmneziaWG не заработает"
[ -e /dev/ppp ]     || mknod /dev/ppp c 108 0 2>/dev/null     || echo "[entrypoint] нет /dev/ppp — L2TP не заработает"

# Агент применения конфига запускается внутри API (lifespan в app/main.py):
# DHCP-клиентом, dnsmasq и VPN-процессами владеет долгоживущий процесс.
exec uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}" --log-level "${LOG_LEVEL:-info}"
