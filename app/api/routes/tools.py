"""
Раздел Tools — сетевая диагностика.

  WS   /api/tools/ws            потоковые инструменты: ping, tcp_ping, traceroute, scan, capture
       клиент шлёт  {"tool": "ping", "params": {...}}, затем при желании {"action": "stop"}
       сервер шлёт  {"type": "row"|"info"|"summary"|"error"|"done", ...}
  GET  /api/tools/neighbors     таблица соседей (ARP)
  GET  /api/tools/dns?host=     разрешение имени
  GET  /api/tools/interfaces    интерфейсы для выбора в формах
  GET  /api/tools/capture.pcap  файл последнего захвата — открыть в Wireshark
"""
import asyncio
import contextlib

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from app.services import netlink, tools

router = APIRouter()


@router.get("/neighbors")
def get_neighbors():
    try:
        return tools.neighbors()
    except tools.ToolError as e:
        raise HTTPException(500, str(e))


@router.get("/dns")
async def get_dns(host: str = Query(...)):
    try:
        return await tools.dns_lookup(host)
    except tools.ToolError as e:
        raise HTTPException(422, str(e))


@router.get("/interfaces")
def get_interfaces():
    return {"interfaces": sorted(n for n in netlink.link_names() if n != "lo"),
            "scan_network": tools.default_scan_network()}


@router.get("/capture.pcap")
def get_capture():
    f = tools.capture_file()
    if not f.exists():
        raise HTTPException(404, "захвата ещё не было")
    return FileResponse(f, media_type="application/vnd.tcpdump.pcap", filename="ubuntu-router-capture.pcap")


@router.websocket("/ws")
async def tools_ws(ws: WebSocket):
    await ws.accept()
    try:
        req = await ws.receive_json()
    except (WebSocketDisconnect, ValueError):
        return
    fn = tools.TOOLS.get(req.get("tool"))
    if not fn:
        await ws.send_json({"type": "error", "text": f"нет инструмента {req.get('tool')}"})
        await ws.close()
        return

    async def run():
        gen = fn(req.get("params") or {})
        try:
            async for event in gen:
                await ws.send_json(event)
        except tools.ToolError as e:
            await ws.send_json({"type": "error", "text": str(e)})
        finally:
            await gen.aclose()          # убить процесс утилиты, если он ещё жив

    async def wait_stop():
        while True:
            msg = await ws.receive_json()
            if msg.get("action") == "stop":
                return

    task = asyncio.create_task(run())
    stopper = asyncio.create_task(wait_stop())
    done, pending = await asyncio.wait({task, stopper}, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, Exception):
            await t
    with contextlib.suppress(Exception):
        await ws.send_json({"type": "done", "stopped": stopper in done})
        await ws.close()
