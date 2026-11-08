"""
Раздел VPN → WireGuard (клиент).

  GET  /api/vpn/wireguard          состояние туннеля и настройки (без приватного ключа)
  PUT  /api/vpn/wireguard          сохранить и применить
  POST /api/vpn/wireguard/parse    разобрать конфиг .conf от сервера (для заполнения формы)
  POST /api/vpn/wireguard/genkey   сгенерировать пару ключей
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.models.wireguard import WgConfig, WgStatus, parse_wg_quick
from app.services import vpn as svc

router = APIRouter()


class ConfText(BaseModel):
    text: str


class KeyPair(BaseModel):
    private_key: str
    public_key: str


@router.get("/wireguard", response_model=WgStatus)
def get_wireguard():
    return svc.status()


@router.put("/wireguard", response_model=WgStatus)
def set_wireguard(data: WgConfig):
    try:
        return svc.update(data)
    except svc.VpnError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.post("/wireguard/parse", response_model=WgConfig)
def parse_conf(body: ConfText):
    try:
        return parse_wg_quick(body.text)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"не удалось разобрать конфиг: {e}")


@router.post("/wireguard/genkey", response_model=KeyPair)
def generate_keys():
    try:
        private, public = svc.genkey()
    except svc.VpnError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return KeyPair(private_key=private, public_key=public)
