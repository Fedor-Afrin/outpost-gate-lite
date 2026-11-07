"""Раздел System: состояние роутера (аналог /system resource)."""
import platform
import socket

from fastapi import APIRouter

from app.core.config import settings
from app.services import sysctl

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/resource")
def resource():
    return {
        "hostname": socket.gethostname(),
        "kernel": platform.release(),
        "version": settings.version,
        "mode": settings.mode,
        "ip_forward": sysctl.get_ip_forward(),
    }
