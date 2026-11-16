# OutpostGate Lite

**A compact VPN gateway for a remote employee**, running in Docker on any Linux box (a VM, a mini PC,
a NanoPi). One WAN to the internet, LAN ports for the phone and the computer, a tunnel to the company
network. You manage it from a web UI, a REST API, or a command line that speaks both
**MikroTik RouterOS** and **Linux** (`ip`, `nmcli`).

The host's Linux kernel does the routing, NAT and firewalling. The container is the control plane.
One configuration file (`router.yaml`) is the source of truth. Every change is validated, applied
atomically and snapshotted, and Safe Mode rolls it back if you lose access.

> OutpostGate Lite is the small sibling of **OutpostGate Pro**, which adds BIND 9 / Kea, dual WAN,
> LAN segments, GRE, OSPF/BGP, QoS and monitoring. Lite stays light on purpose: **dnsmasq** for DHCP
> and DNS, a single WAN and a single LAN.

---

## What it can do

### Network
- **WAN**: DHCP, static, or left to the system.
- **LAN**: a bridge of the chosen ports. **dnsmasq** provides DHCP (pool, lease time, static leases)
  and a caching DNS. Devices are reachable by name: `nas`, `nas.lan`.
  If you change the LAN network, the DHCP pool and the static leases move to the new network.
- **Firewall & NAT (nftables)**: zone rules (WAN / LAN / VPN), port forwarding **from WAN or from the
  VPN tunnel**, lockout protection, counters, and a plain-language view of what the system rules do.
- **Tools**: ping, traceroute, port scan, network scan, DNS lookup, ARP neighbours. Names resolve
  through the router's own DNS, the same way LAN devices see them.

### VPN: three tunnel types, one active at a time
| Tunnel | Notes |
|---|---|
| **WireGuard** | import a `.conf`; full or split tunnel |
| **AmneziaWG** (up to 3.1) | DPI-resistant WireGuard; paste a `vpn://` link or `.vpn` file straight from the Amnezia app |
| **L2TP/IPsec** | strongSwan + xl2tpd, the classic corporate VPN |

- **Full or split tunnel**, kill switch, NAT or site-to-site mode.
- **Watchdog**: the tunnel reconnects by itself, with back-off, when the server goes silent. For
  WireGuard/AmneziaWG that means no handshake for 3.5 minutes (host sleep, network change, a crashed
  `amneziawg-go`). For L2TP it means PPP is not up.
  The web UI and `/vpn print` show how many reconnects happened and why.
- **Remote access through the tunnel**: manage the router (web, SSH, CLI, ping) from a phone on the
  same VPN server, and forward ports from the tunnel to LAN devices (a PBX, a camera, a NAS).
- **The router's own traffic bypasses a full tunnel**: updates, Docker Hub and apt go straight
  through WAN, so maintenance never depends on the VPN. LAN devices still use the tunnel.

### Operations
Users with full or read-only roles, an audit log, backup/restore of `router.yaml`, automatic
snapshots, Safe Mode, an installer for VMs and servers.

---

## Command line: RouterOS or Linux, your choice

Connect with `ssh -p 2222 admin@192.168.88.1`. On the first login the CLI asks which syntax you
prefer. Switch any time with `linux` or `routeros`.

**MikroTik RouterOS style**: menus, abbreviations, `print detail`, row numbers, Tab completion.
```
[admin@office] > /ip address print
[admin@office] > /ip firewall nat add chain=dstnat action=dst-nat protocol=udp dst-port=5060 to-addresses=192.168.88.20 in-interface-list=VPN
[admin@office] > /vpn print
[admin@office] > :resolve nas
```

**Linux style**: viewing commands run the real tools. Changes go through the router configuration,
so nothing is lost on the next apply.
```
admin@office:~$ ip -br a
admin@office:~$ ip route add 192.168.20.0/24 via 10.8.1.1
admin@office:~$ nmcli c
admin@office:~$ nmcli c mod lan ipv4.addresses 192.168.1.1/24
admin@office:~$ nmcli c up amneziawg
admin@office:~$ ping -c 3 nas
```
- Interactive sessions get an Ubuntu-style colored prompt and colored output (iproute2 colors,
  nmcli states). Scripts get plain text.
- Hints, help and messages come in **English, Russian or Hebrew**: switch with `sl1`, `sl2`, `sl3`.
- `/…` runs a RouterOS command from the Linux syntax too.
- **Ansible**: log in as `admin+cet1024w`, as `community.routeros` recommends, and you get a plain
  RouterOS session with no questions. `without-paging` is accepted. Everything is also available
  through the REST API.

---

## Web UI and API
- Web UI on **port 80** (`http://<router LAN address>`), in English, Russian and Hebrew
  (right-to-left), switchable without a reload.
- REST API (FastAPI) on the same port. Interactive docs are at `/docs`.
- First login: user `admin` with an empty password, allowed only from the LAN until you set a password.

## Technologies
| Layer | Stack |
|---|---|
| Control plane | Python 3.12, FastAPI, Pydantic v2, uvicorn, pyroute2, asyncssh, prompt_toolkit |
| Web UI | plain HTML/CSS/JavaScript, no build step; i18n dictionary in `web/js/i18n-dict.js` |
| Data plane | Linux kernel: bridge, nftables, policy routing |
| Services | dnsmasq (DHCP + DNS) |
| VPN | wireguard-tools, amneziawg-go / amneziawg-tools, strongSwan + xl2tpd |
| Packaging | Docker (one image, three run modes), Bash installer |
| Tests | pytest (models, firewall rulesets, CLI in both syntaxes, VPN watchdog, LAN, tools, installer) |

## Run modes (one image)
| Mode | Where | Network | Files |
|---|---|---|---|
| dev | your workstation | its own namespace; the host is untouched | `docker-compose.yml` |
| gns3 | a GNS3 Docker node | its own namespace, eth0..N from GNS3 | `deploy/gns3/` |
| host | VM / server / bare metal | the server's network (`network_mode: host`) | `deploy/host/`, `install.sh` |

### Quick start (dev)
```bash
docker compose up --build
```
Web UI: http://localhost:8001 · API docs: http://localhost:8001/docs · CLI: `ssh -p 2222 admin@localhost`

### Install on a VM or server
Ubuntu 22.04/24.04 or Debian 12/13 with at least two network adapters:
```bash
cd outpost-gate
sudo ./install.sh                    # wizard: WAN, LAN, admin password
sudo ./install.sh --status
sudo ./install.sh --update           # rebuild and restart after pulling new code
sudo ./install.sh --update --api-port 8080   # move the web UI to another port
sudo ./install.sh --uninstall        # --purge also removes the settings
```
Unattended: `sudo ./install.sh -y --wan ens18 --wan-mode none --lan ens19 --password '...'` (see `--help`).

The installer:
- loads the kernel modules and sets the sysctls;
- hands the router's ports over from netplan / NetworkManager;
- keeps Docker out of the firewall and clears a leftover `FORWARD DROP`;
- gives the server its own DNS;
- builds the image in the host network.

## Project layout
```
app/api/        REST endpoints (FastAPI routers)
app/models/     Pydantic models: validation of every config section
app/services/   apply logic: nftables, netlink, dnsmasq, VPN (+ watchdog), tools
app/cli/        SSH command line: RouterOS syntax (commands.py), Linux syntax (linux.py), colors/i18n (term.py)
web/            web UI
deploy/         run modes: host, gns3
install.sh      installer for VMs and servers
tests/          pytest
```

## Author
Fedor Afrin, network & telecom engineer. Built with the help of Claude (Anthropic).
