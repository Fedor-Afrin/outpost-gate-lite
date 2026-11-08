"""
Tools — сетевая диагностика (без Nmap: только стандартные утилиты и свой код).

  ping        — ICMP (iputils ping)
  tcp_ping    — время установления TCP-соединения с host:port (свой код)
  traceroute  — маршрут до узла (UDP, ICMP или TCP)
  dns         — разрешение имени через DNS роутера
  neighbors   — таблица соседей (ARP): IP, MAC, производитель, имя из DHCP
  scan        — сканер подсети: ping-обход + ARP (видит и тех, кто не отвечает на ping) + TCP-порты
  capture     — захват пакетов tcpdump: строки в реальном времени + файл .pcap для Wireshark

Потоковые инструменты — асинхронные генераторы событий:
  {"type": "row", "row": {...}}      строка таблицы
  {"type": "info", "text": "..."}    служебное сообщение
  {"type": "summary", "data": {...}} итог
Процесс утилиты завершается, когда генератор закрыт (кнопка «Стоп» или закрытая вкладка).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import shlex
import socket
import subprocess
import time
from pathlib import Path
from typing import AsyncIterator

from app.core.config import settings
from app.services import oui

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")
IFACE_RE = re.compile(r"^[A-Za-z0-9_.@:-]{1,15}$")
MAX_SCAN_HOSTS = 1024
MAX_CAPTURE_PACKETS = 2000
MAX_CAPTURE_SECONDS = 120


class ToolError(Exception):
    pass


# --- проверка ввода (команды запускаются без shell, но аргументы всё равно проверяем) ----------
def check_host(host: str) -> str:
    host = (host or "").strip()
    if not HOST_RE.match(host) or host.startswith("-"):
        raise ToolError(f"неверный адрес или имя: '{host}'")
    return host


def check_int(value, lo: int, hi: int, what: str) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError) as e:
        raise ToolError(f"{what}: нужно число") from e
    if not lo <= v <= hi:
        raise ToolError(f"{what}: от {lo} до {hi}")
    return v


def check_iface(iface: str | None) -> str | None:
    if not iface or iface == "auto":
        return None
    if not IFACE_RE.match(iface) or iface.startswith("-"):
        raise ToolError(f"неверный интерфейс: '{iface}'")
    return iface


def parse_ports(text: str | None, limit: int = 32) -> list[int]:
    ports: list[int] = []
    for item in (text or "").replace(" ", "").split(","):
        if not item:
            continue
        if "-" in item:
            a, b = (check_int(x, 1, 65535, "порт") for x in item.split("-", 1))
            ports += list(range(a, b + 1))
        else:
            ports.append(check_int(item, 1, 65535, "порт"))
    if len(ports) > limit:
        raise ToolError(f"не больше {limit} портов за раз")
    return sorted(set(ports))


# --- запуск утилиты построчно -----------------------------------------------------------------
async def run_lines(cmd: list[str], timeout: float) -> AsyncIterator[str]:
    """Строки вывода команды; по таймауту или закрытию генератора процесс убивается."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    except FileNotFoundError as e:
        raise ToolError(f"нет программы {cmd[0]}") from e
    deadline = time.monotonic() + timeout
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=left)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            yield line.decode(errors="replace").rstrip()
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()


# --- ping ------------------------------------------------------------------------------------
PING_REPLY = re.compile(r"from ([\d.]+).*icmp_seq=(\d+) ttl=(\d+) time=([\d.]+) ms")
PING_LOST = re.compile(r"no answer yet for icmp_seq=(\d+)")
PING_ERR = re.compile(r"From ([\d.]+) icmp_seq=(\d+) (.+)")
PING_STATS = re.compile(r"(\d+) packets transmitted, (\d+) received.*?([\d.]+)% packet loss")
PING_RTT = re.compile(r"= ([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+) ms")


def parse_ping_line(line: str) -> dict | None:
    if m := PING_REPLY.search(line):
        return {"type": "row", "row": {"seq": int(m[2]), "from": m[1], "ttl": int(m[3]),
                                       "time_ms": float(m[4]), "status": "ok"}}
    if m := PING_LOST.search(line):
        return {"type": "row", "row": {"seq": int(m[1]), "status": "timeout"}}
    if m := PING_ERR.search(line):
        return {"type": "row", "row": {"seq": int(m[2]), "from": m[1], "status": m[3].strip()}}
    if m := PING_STATS.search(line):
        return {"type": "summary", "data": {"sent": int(m[1]), "received": int(m[2]), "loss": float(m[3])}}
    if m := PING_RTT.search(line):
        return {"type": "summary", "data": {"min": float(m[1]), "avg": float(m[2]), "max": float(m[3])}}
    if line.startswith("ping:"):
        return {"type": "error", "text": line}
    return None


async def ping(params: dict) -> AsyncIterator[dict]:
    host = check_host(params.get("host"))
    count = check_int(params.get("count", 4), 1, 100, "количество")
    size = check_int(params.get("size", 56), 8, 1472, "размер")
    cmd = ["ping", "-n", "-O", "-c", str(count), "-W", "2", "-i", "0.5", "-s", str(size)]
    if iface := check_iface(params.get("interface")):
        cmd += ["-I", iface]
    async for line in run_lines(cmd + [host], timeout=count * 0.5 + 5):
        if ev := parse_ping_line(line):
            yield ev


# --- TCP ping ----------------------------------------------------------------------------------
async def tcp_probe(host: str, port: int, timeout: float = 2.0) -> tuple[str, float | None]:
    """('open' | 'closed' | 'timeout' | ошибка, время мс)."""
    start = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    except asyncio.TimeoutError:
        return "timeout", None
    except ConnectionRefusedError:
        return "closed", round((time.perf_counter() - start) * 1000, 2)
    except OSError as e:
        return e.strerror or str(e), None
    ms = round((time.perf_counter() - start) * 1000, 2)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    return "open", ms


async def tcp_ping(params: dict) -> AsyncIterator[dict]:
    host = check_host(params.get("host"))
    port = check_int(params.get("port", 443), 1, 65535, "порт")
    count = check_int(params.get("count", 4), 1, 100, "количество")
    times = []
    for seq in range(1, count + 1):
        status, ms = await tcp_probe(host, port)
        if ms is not None and status == "open":
            times.append(ms)
        yield {"type": "row", "row": {"seq": seq, "port": port, "status": status, "time_ms": ms}}
        if seq < count:
            await asyncio.sleep(1)
    yield {"type": "summary", "data": {"sent": count, "received": len(times),
                                       "loss": round(100 * (count - len(times)) / count, 1),
                                       **({"min": min(times), "avg": round(sum(times) / len(times), 2),
                                           "max": max(times)} if times else {})}}


# --- traceroute -----------------------------------------------------------------------------------
def parse_traceroute_line(line: str) -> dict | None:
    """' 3  10.0.0.1  5.123 ms  4.9 ms *' -> {'hop': 3, 'ip': '10.0.0.1', 'times': [5.123, 4.9, None]}"""
    tokens = line.split()
    if not tokens or not tokens[0].isdigit():
        return None
    hop, ips, times, notes = int(tokens[0]), [], [], []
    i = 1
    while i < len(tokens):
        t = tokens[i]
        if t == "*":
            times.append(None)
        elif i + 1 < len(tokens) and tokens[i + 1] == "ms":
            times.append(float(t))
            i += 1
        elif t.startswith("!"):
            notes.append(t)
        else:
            try:
                ipaddress.ip_address(t)
                ips.append(t)
            except ValueError:
                pass
        i += 1
    return {"hop": hop, "ip": ips[0] if ips else None, "other_ips": ips[1:], "times": times, "notes": notes}


async def traceroute(params: dict) -> AsyncIterator[dict]:
    host = check_host(params.get("host"))
    max_hops = check_int(params.get("max_hops", 30), 1, 64, "максимум хопов")
    method = params.get("method", "udp")
    cmd = ["traceroute", "-n", "-q", "3", "-w", "2", "-m", str(max_hops)]
    if method == "icmp":
        cmd.append("-I")
    elif method == "tcp":
        cmd += ["-T", "-p", str(check_int(params.get("port", 443), 1, 65535, "порт"))]
    if iface := check_iface(params.get("interface")):
        cmd += ["-i", iface]
    async for line in run_lines(cmd + [host], timeout=max_hops * 7 + 5):
        if row := parse_traceroute_line(line):
            yield {"type": "row", "row": row}
        elif line.startswith("traceroute to"):
            yield {"type": "info", "text": line}
        elif line.strip():
            yield {"type": "error", "text": line}


# --- DNS ----------------------------------------------------------------------------------------
async def dns_lookup(host: str) -> dict:
    host = check_host(host)
    loop = asyncio.get_running_loop()
    start = time.perf_counter()
    try:
        infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return {"host": host, "addresses": [], "error": e.strerror, "time_ms": None}
    ms = round((time.perf_counter() - start) * 1000, 2)
    addrs = sorted({i[4][0] for i in infos}, key=lambda a: (":" in a, a))
    return {"host": host, "addresses": addrs, "error": None, "time_ms": ms}


# --- соседи (ARP) ------------------------------------------------------------------------------
def _names() -> dict[str, str]:
    """MAC -> имя: из закреплённых адресов и DHCP-аренд LAN."""
    try:
        from app.services import lan
        names = {l.mac: (l.name or l.hostname) for l in lan.leases() if l.name or l.hostname}
        names.update({s.mac: s.name for s in lan.static_leases() if s.name})
        return names
    except Exception:
        return {}


def parse_neighbors(data: list[dict], names: dict[str, str] | None = None) -> list[dict]:
    names = names or {}
    out = []
    for n in data:
        dst = n.get("dst", "")
        if ":" in dst:          # IPv6 соседей пока не показываем
            continue
        mac = (n.get("lladdr") or "").lower() or None
        out.append({
            "ip": dst, "interface": n.get("dev"), "mac": mac,
            "state": ",".join(n.get("state", [])) or None,
            "vendor": oui.vendor(mac) if mac else None,
            "name": names.get(mac) if mac else None,
        })
    return sorted(out, key=lambda x: tuple(int(p) for p in x["ip"].split(".")))


def neighbors() -> list[dict]:
    try:
        r = subprocess.run(["ip", "-j", "-4", "neigh", "show"], capture_output=True, text=True, timeout=5)
    except FileNotFoundError as e:
        raise ToolError("нет программы ip") from e
    return parse_neighbors(json.loads(r.stdout or "[]"), _names())


# --- сканер подсети -------------------------------------------------------------------------------
async def _ping_once(ip: str) -> float | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "-c", "1", "-W", "1", ip,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    except FileNotFoundError as e:
        raise ToolError("нет программы ping") from e
    out, _ = await proc.communicate()
    m = PING_REPLY.search(out.decode(errors="replace"))
    return float(m[4]) if m else None


def default_scan_network() -> str | None:
    try:
        from app.services import lan
        cfg = lan.get_config()
        return str(ipaddress.ip_interface(cfg.address).network) if cfg.enabled else None
    except Exception:
        return None


async def scan(params: dict) -> AsyncIterator[dict]:
    try:
        net = ipaddress.ip_network((params.get("network") or default_scan_network() or "").strip(), strict=False)
    except ValueError as e:
        raise ToolError("укажите сеть, например 192.168.88.0/24") from e
    if net.version != 4 or net.num_addresses > MAX_SCAN_HOSTS + 2:
        raise ToolError(f"сеть IPv4 не больше {MAX_SCAN_HOSTS} адресов (/22)")
    ports = parse_ports(params.get("ports"))
    hosts = [str(h) for h in net.hosts()]
    yield {"type": "info", "text": f"Сканирую {net}: {len(hosts)} адресов"
                                   + (f", порты {', '.join(map(str, ports))}" if ports else "")}

    found: dict[str, dict] = {}
    sem = asyncio.Semaphore(64)

    async def probe(ip: str):
        async with sem:
            return ip, await _ping_once(ip)

    # 1) ping-обход — заодно ядро разошлёт ARP-запросы всем адресам
    for fut in asyncio.as_completed([probe(ip) for ip in hosts]):
        ip, ms = await fut
        if ms is not None:
            found[ip] = {"ip": ip, "ping_ms": ms, "source": "ping"}

    # 2) ARP: устройства, которые не отвечают на ping, но ответили на ARP (телефоны, Windows)
    loop = asyncio.get_running_loop()
    try:
        neigh = await loop.run_in_executor(None, neighbors)
    except ToolError:
        neigh = []
    for n in neigh:
        if n["mac"] and ipaddress.ip_address(n["ip"]) in net and n["state"] not in ("FAILED", "INCOMPLETE"):
            row = found.setdefault(n["ip"], {"ip": n["ip"], "ping_ms": None, "source": "arp"})
            row.update(mac=n["mac"], vendor=n["vendor"], name=n["name"], interface=n["interface"])

    # 3) TCP-порты найденных устройств
    for ip in sorted(found, key=lambda a: tuple(int(p) for p in a.split("."))):
        row = found[ip]
        if ports:
            results = await asyncio.gather(*(tcp_probe(ip, p, 1.0) for p in ports))
            row["open_ports"] = [p for p, (st, _) in zip(ports, results) if st == "open"]
        yield {"type": "row", "row": row}
    yield {"type": "summary", "data": {"network": str(net), "scanned": len(hosts), "found": len(found)}}


# --- захват пакетов --------------------------------------------------------------------------------
TCPDUMP_LINE = re.compile(
    r"^(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\s+(?:(?P<iface>\S+)\s+(?P<dir>In|Out|M|P|B)\s+)?"
    r"(?P<l3>IP6?|ARP|LLDP|STP)?,?\s*(?P<rest>.*)$")


def _split_addr(addr: str) -> tuple[str, str | None]:
    """'192.168.88.20.5060' -> ('192.168.88.20', '5060')"""
    parts = addr.rstrip(":").split(".")
    if len(parts) == 5:
        return ".".join(parts[:4]), parts[4]
    return addr.rstrip(":"), None


def parse_tcpdump_line(line: str) -> dict | None:
    m = TCPDUMP_LINE.match(line)
    if not m or not m["time"]:
        return None
    row = {"time": m["time"], "interface": m["iface"], "direction": m["dir"], "proto": m["l3"] or "?",
           "src": None, "dst": None, "info": m["rest"]}
    rest = m["rest"]
    if m["l3"] in ("IP", "IP6") and " > " in rest:
        src, _, tail = rest.partition(" > ")
        dst, _, info = tail.partition(": ")
        (s_ip, s_port), (d_ip, d_port) = _split_addr(src), _split_addr(dst)
        row.update(src=s_ip + (f":{s_port}" if s_port else ""), dst=d_ip + (f":{d_port}" if d_port else ""),
                   info=info)
        low = info.lower()
        if info.startswith("Flags"):
            row["proto"] = "TCP"
        elif low.startswith("icmp"):
            row["proto"] = "ICMP"
        elif "udp" in low or (s_port and d_port):
            row["proto"] = "UDP"
        for port, name in (("53", "DNS"), ("67", "DHCP"), ("68", "DHCP"), ("5060", "SIP"),
                           ("51820", "WireGuard"), ("500", "IKE"), ("4500", "IPsec"), ("1701", "L2TP")):
            if port in (s_port, d_port):
                row["proto"] = name
                break
    elif m["l3"] == "ARP":
        row["info"] = rest.split(", length")[0]
    return row


def capture_file() -> Path:
    return Path(settings.data_dir) / "capture.pcap"


async def capture(params: dict) -> AsyncIterator[dict]:
    iface = check_iface(params.get("interface")) or "any"
    count = check_int(params.get("count", 200), 1, MAX_CAPTURE_PACKETS, "пакетов")
    seconds = check_int(params.get("seconds", 30), 1, MAX_CAPTURE_SECONDS, "секунд")
    filt = shlex.split(params.get("filter") or "")
    if any(t.startswith("-") for t in filt):
        raise ToolError("фильтр — выражение BPF без ключей, например: host 192.168.88.20 and port 5060")
    out = capture_file()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["tcpdump", "-i", iface, "-n", "-l", "-U", "-c", str(count), "-w", str(out), "--print", "--", *filt]
    yield {"type": "info", "text": f"tcpdump на {iface}: до {count} пакетов или {seconds} с"
                                   + (f", фильтр: {' '.join(filt)}" if filt else "")}
    packets = 0
    async for line in run_lines(cmd, timeout=seconds):
        if row := parse_tcpdump_line(line):
            packets += 1
            yield {"type": "row", "row": row}
        elif line.startswith("tcpdump:") and ("error" in line or "syntax" in line or "No such" in line):
            yield {"type": "error", "text": line}
    yield {"type": "summary", "data": {"packets": packets, "pcap": out.exists() and out.stat().st_size > 24}}


TOOLS = {"ping": ping, "tcp_ping": tcp_ping, "traceroute": traceroute, "scan": scan, "capture": capture}
