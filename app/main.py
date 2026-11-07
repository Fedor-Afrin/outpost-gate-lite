"""Точка входа FastAPI-приложения Ubuntu Router."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes import interfaces, system
from app.core.config import settings

app = FastAPI(
    title="Ubuntu Router",
    version=settings.version,
    description="Роутер на Ubuntu: управление через REST API (идеи RouterOS)",
)

# API — разделы как в меню RouterOS
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(interfaces.router, prefix="/api/interfaces", tags=["Interfaces"])
# Следующие этапы: ip/addresses, ip/routes, ip/firewall, ip/dhcp-server, tools

# Веб-интерфейс (статические файлы) — монтируется последним
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
