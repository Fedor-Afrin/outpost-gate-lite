"""Точка входа FastAPI-приложения Ubuntu Router."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import interfaces, ip_addresses, ip_routes, system
from app.core.config import settings

app = FastAPI(
    title="Ubuntu Router",
    version=settings.version,
    description="Роутер на Ubuntu: управление через REST API (идеи RouterOS)",
)

# API — разделы как в меню RouterOS
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(interfaces.router, prefix="/api/interfaces", tags=["Interfaces"])
app.include_router(ip_addresses.router, prefix="/api/ip/addresses", tags=["IP / Addresses"])
app.include_router(ip_routes.router, prefix="/api/ip/routes", tags=["IP / Routes"])
# Следующие шаги этапа 1: ip/dhcp-client, ip/dhcp-server, ip/dns

# Веб-интерфейс (статические файлы) — монтируется последним
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
