"""Установщик: первый router.yaml (app.scripts.initconfig) и порты управления сервера."""
import json
import subprocess
from pathlib import Path

from app.scripts import initconfig
from app.services import firewall

ROOT = Path(__file__).resolve().parents[1]


def test_initconfig_and_host_ssh_port(monkeypatch):
    d = initconfig.build({"identity": "office", "wan": {"interface": "ens18", "mode": "none"},
                          "lan": {"address": "192.168.88.1/24", "ports": ["ens19"], "wan_management": True}})
    assert d["wan"] == {"interface": "ens18", "mode": "none"} and d["system"]["identity"] == "office"
    assert d["lan"]["ports"] == ["ens19"] and d["lan"]["enabled"] is True
    assert d["firewall"] == {"wan-management": True}
    assert initconfig.build({"wan": {"interface": "ens18", "mode": "dhcp"}, "lan": {}})["lan"]["enabled"] is False
    assert initconfig.main(["x", json.dumps({"wan": {"interface": "ens18", "mode": "static"}, "lan": {}})]) == 2
    monkeypatch.setenv("HOST_SSH_PORT", "22")
    monkeypatch.setenv("CLI_SSH_PORT", "2222")
    monkeypatch.delenv("API_PORT", raising=False)
    assert firewall.management_ports() == [22, 80, 2222]


def test_install_script_syntax():
    assert subprocess.run(["bash", "-n", str(ROOT / "install.sh")]).returncode == 0
    text = (ROOT / "install.sh").read_text()
    assert "WAN2" not in text and "ip_gre" not in text and "outpost_gate_lite" in text
    assert "docker build --network host" in text and "FORWARD ACCEPT" in text
