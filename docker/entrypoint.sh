#!/bin/sh
set -e
echo "[entrypoint] Ubuntu Router, mode=${ROUTER_MODE}"

# Агент: привести систему к конфигу (пока только ip_forward)
python -m app.agent.apply

exec uvicorn app.main:app --host "${API_HOST}" --port "${API_PORT}" --log-level "${LOG_LEVEL:-info}"
