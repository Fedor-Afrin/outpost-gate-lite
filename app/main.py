"""Точка входа FastAPI-приложения Ubuntu Router."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.agent import apply as agent
from app.api.routes import auth as auth_routes
from app.api.routes import firewall, interfaces, ip_addresses, ip_routes, lan, system, tools, vpn, wan
from app.core import auth
from app.core.config import settings
from app.services import system as system_svc
from app.services import lan as lan_svc
from app.services import vpn as vpn_svc
from app.services import wan as wan_svc


@asynccontextmanager
async def lifespan(_: FastAPI):
    auth.ensure_admin()                        # первый запуск: admin + пароль в docker logs
    system_svc.safe_mode.recover_on_startup()  # перезапуск посреди Safe Mode = откат
    # Агент работает внутри процесса API: DHCP-клиентом WAN управляет этот процесс
    agent.apply_startup()
    yield
    vpn_svc.stop_all()
    lan_svc.stop_dnsmasq()
    wan_svc.stop_dhcp()   # корректно отпустить аренду при остановке


app = FastAPI(
    title="Ubuntu Router",
    version=settings.version,
    description="VPN-шлюз на Ubuntu: управление через REST API (идеи RouterOS)",
    lifespan=lifespan,
)


@app.middleware("http")
async def security(request: Request, call_next):
    """Вход и права для /api, журнал изменений, свежие веб-файлы."""
    path, method = request.url.path, request.method
    user = auth.user_from_token(auth.token_from(request.cookies, request.headers)) if path.startswith("/api") else None
    if denied := auth.check_access(path, method, user):
        return JSONResponse(status_code=denied[0], content={"detail": denied[1]})
    request.state.user = user.name if user else "-"

    response = await call_next(request)

    if path.startswith("/api") and method in ("POST", "PUT", "PATCH", "DELETE") \
            and not path.startswith("/api/auth/"):
        system_svc.audit(request.state.user, method, path, response.status_code,
                         request.client.host if request.client else "-")
    if not path.startswith("/api"):
        # браузер всегда сверяет веб-файлы с сервером — после обновления не будет старого app.js
        response.headers["Cache-Control"] = "no-cache"
    return response


# API: основные разделы
app.include_router(auth_routes.router, prefix="/api/auth", tags=["Auth"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(wan.router, prefix="/api/wan", tags=["WAN"])
app.include_router(lan.router, prefix="/api/lan", tags=["LAN"])
app.include_router(vpn.router, prefix="/api/vpn", tags=["VPN"])
app.include_router(firewall.router, prefix="/api/firewall", tags=["Firewall"])
app.include_router(tools.router, prefix="/api/tools", tags=["Tools"])

# API: Advanced (двигатель под WAN / LAN / VPN)
app.include_router(interfaces.router, prefix="/api/interfaces", tags=["Advanced / Interfaces"])
app.include_router(ip_addresses.router, prefix="/api/ip/addresses", tags=["Advanced / IP Addresses"])
app.include_router(ip_routes.router, prefix="/api/ip/routes", tags=["Advanced / IP Routes"])

# Веб-интерфейс (статические файлы) — монтируется последним
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
