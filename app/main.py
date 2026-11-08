"""Точка входа FastAPI-приложения Ubuntu Router."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.agent import apply as agent
from app.api.routes import interfaces, ip_addresses, ip_routes, lan, system, vpn, wan
from app.core.config import settings
from app.services import lan as lan_svc
from app.services import wan as wan_svc


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Агент работает внутри процесса API: DHCP-клиентом WAN управляет этот процесс
    agent.apply_startup()
    yield
    lan_svc.stop_dnsmasq()
    wan_svc.stop_dhcp()   # корректно отпустить аренду при остановке


app = FastAPI(
    title="Ubuntu Router",
    version=settings.version,
    description="VPN-шлюз на Ubuntu: управление через REST API (идеи RouterOS)",
    lifespan=lifespan,
)


@app.middleware("http")
async def no_stale_web(request: Request, call_next):
    """Браузер всегда сверяет веб-файлы с сервером — после обновления не будет старого app.js."""
    response = await call_next(request)
    if not request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# API: основные разделы
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(wan.router, prefix="/api/wan", tags=["WAN"])
app.include_router(lan.router, prefix="/api/lan", tags=["LAN"])
app.include_router(vpn.router, prefix="/api/vpn", tags=["VPN"])

# API: Advanced (двигатель под WAN / LAN / VPN)
app.include_router(interfaces.router, prefix="/api/interfaces", tags=["Advanced / Interfaces"])
app.include_router(ip_addresses.router, prefix="/api/ip/addresses", tags=["Advanced / IP Addresses"])
app.include_router(ip_routes.router, prefix="/api/ip/routes", tags=["Advanced / IP Routes"])

# Веб-интерфейс (статические файлы) — монтируется последним
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
