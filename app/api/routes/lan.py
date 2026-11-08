"""
Раздел LAN.

  GET /api/lan   состояние: мост, порты (с ролями WAN/LAN), DHCP-аренды
  PUT /api/lan   сохранить настройки и применить (мост, dnsmasq, NAT, фаервол)
"""
from fastapi import APIRouter, HTTPException

from app.models.lan import LanConfig, LanStatus
from app.services import lan as svc

router = APIRouter()


@router.get("", response_model=LanStatus)
def get_lan():
    return svc.status()


@router.put("", response_model=LanStatus)
def set_lan(data: LanConfig):
    try:
        return svc.update(data)
    except svc.LanError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
