#!/bin/sh
set -e
echo "[entrypoint] Ubuntu Router, mode=${ROUTER_MODE}"

# Агент применения конфига запускается внутри API (lifespan в app/main.py):
# DHCP-клиентом WAN должен владеть долгоживущий процесс.
exec uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}" --log-level "${LOG_LEVEL:-info}"
