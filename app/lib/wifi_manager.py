"""
KVMind Integration - WiFi Manager

Provides WiFi scanning and connection management for the device setup wizard.
Uses iw for scanning/status, direct wpa_supplicant.conf editing for connection.

Note: wpa_cli control socket is unreliable from systemd services on PiKVM
(STATUS command timed out), so we bypass it entirely and edit the config file
+ restart wpa_supplicant@wlan0 service instead.

API:
    GET  /api/wifi/scan       → list available networks
    GET  /api/wifi/status     → current connection status + IP
    POST /api/wifi/connect    → connect to SSID with password
    POST /api/wifi/disconnect → disconnect
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .remount import async_remount_rw

log = logging.getLogger(__name__)

INTERFACE = "wlan0"
WPA_CONF = "/etc/wpa_supplicant/wpa_supplicant-wlan0.conf"


@dataclass
class WiFiNetwork:
    ssid: str
    signal: int          # 0-100 (converted from dBm)
    security: str        # WPA2, WPA3, Open, …
    connected: bool = False

    def as_dict(self) -> dict:
        return {
            "ssid": self.ssid,
            "signal": self.signal,
            "security": self.security,
            "connected": self.connected,
        }


@dataclass
class WiFiStatus:
    connected: bool
    ssid: Optional[str]
    ip_address: Optional[str]
    interface: Optional[str]

    def as_dict(self) -> dict:
        return {
            "connected": self.connected,
            "ssid": self.ssid,
            "ip_address": self.ip_address,
            "interface": self.interface,
        }


async def _run(cmd: list[str]) -> tuple[int, str, str]:
    """Run a command (as arg list), return (returncode, stdout, stderr).

    Uses create_subprocess_exec to avoid shell injection.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")



def _dbm_to_percent(dbm: float) -> int:
    """Convert dBm signal strength to 0-100 percentage."""
    # Typical range: -90 dBm (weak) to -30 dBm (strong)
    if dbm >= -30:
        return 100
    if dbm <= -90:
        return 0
    return int(100 * (dbm + 90) / 60)


def _parse_iw_scan(output: str, connected_ssid: Optional[str] = None) -> List[WiFiNetwork]:
    """Parse `iw dev wlan0 scan` output into WiFiNetwork list."""
    networks: List[WiFiNetwork] = []
    seen: set = set()

    # Split by BSS entries
    blocks = re.split(r'^BSS ', output, flags=re.MULTILINE)

    for block in blocks:
        if not block.strip():
            continue

        # SSID
        ssid_match = re.search(r'^\tSSID: (.+)$', block, re.MULTILINE)
        if not ssid_match:
            continue
        ssid = ssid_match.group(1).strip()
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)

        # Signal
        sig_match = re.search(r'signal: ([-\d.]+)', block)
        dbm = float(sig_match.group(1)) if sig_match else -90.0
        signal = _dbm_to_percent(dbm)

        # Security
        security = "Open"
        if "WPA3" in ssid:
            # Some routers append -WPA3 to SSID for their WPA3 network
            security = "WPA3"
        if re.search(r'RSN:', block):
            # RSN = WPA2/WPA3
            if re.search(r'SAE', block):
                security = "WPA3"
            else:
                security = "WPA2"
        elif re.search(r'WPA:', block):
            security = "WPA"
        elif 'Privacy' in block:
            security = "WEP"

        # Connected?
        is_connected = ("-- associated" in block) or (ssid == connected_ssid)

        networks.append(WiFiNetwork(
            ssid=ssid,
            signal=signal,
            security=security,
            connected=is_connected,
        ))

    networks.sort(key=lambda n: n.signal, reverse=True)
    return networks


class WiFiManager:
    """
    Manages WiFi via iw + wpa_cli on Arch Linux (PiKVM OS).
    """

    async def scan(self) -> List[WiFiNetwork]:
        """Return list of visible WiFi networks sorted by signal strength."""
        # PiKVM leaves wlan0 DOWN by default (wpa_supplicant@wlan0 is disabled
        # until the user connects), so `iw scan` fails with "Network is down".
        # Bring the interface up idempotently before scanning.
        await _run(["ip", "link", "set", INTERFACE, "up"])

        # Get currently connected SSID
        connected_ssid = None
        rc, stdout, _ = await _run(["iw", "dev", INTERFACE, "link"])
        if rc == 0 and "Connected" in stdout:
            for line in stdout.splitlines():
                line = line.strip()
                if line.startswith("SSID:"):
                    connected_ssid = line.split(":", 1)[1].strip()
                    break

        # Run scan
        rc, stdout, stderr = await _run(["iw", "dev", INTERFACE, "scan"])
        if rc != 0:
            # iw scan may fail if device is busy, try with cached results
            log.warning("iw scan failed (rc=%d): %s, trying dump", rc, stderr.strip())
            rc, stdout, _ = await _run(["iw", "dev", INTERFACE, "scan", "dump"])
            if rc != 0:
                log.error("iw scan dump also failed")
                return []

        networks = _parse_iw_scan(stdout, connected_ssid)
        log.info("WiFi scan found %d networks", len(networks))
        return networks

    async def status(self) -> WiFiStatus:
        """Return current WiFi connection status using iw + ip commands."""
        # Get connected SSID from iw
        rc, stdout, _ = await _run(["iw", "dev", INTERFACE, "link"])
        ssid = None
        if rc == 0 and "Connected" in stdout:
            for line in stdout.splitlines():
                line = line.strip()
                if line.startswith("SSID:"):
                    ssid = line.split(":", 1)[1].strip()
                    break

        # Get IP address
        ip_address = None
        _, ip_out, _ = await _run(["ip", "-4", "addr", "show", INTERFACE])
        match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/", ip_out)
        if match:
            ip_address = match.group(1)

        connected = ssid is not None and ip_address is not None

        return WiFiStatus(
            connected=connected,
            ssid=ssid,
            ip_address=ip_address,
            interface=INTERFACE if connected else None,
        )

    async def connect(self, ssid: str, password: str) -> dict:
        """
        Connect to a WiFi network by editing wpa_supplicant.conf and restarting.

        Bypasses wpa_cli (unreliable from systemd) — directly writes config file.
        """
        log.info("WiFiManager.connect: ssid=%r", ssid)

        # 1. Generate network block
        if password:
            # Use wpa_passphrase to hash the PSK — exec avoids shell injection
            rc, stdout, stderr = await _run(
                ["wpa_passphrase", ssid, password]
            )
            if rc != 0 or "network=" not in stdout:
                log.error("wpa_passphrase failed: rc=%d stderr=%r", rc, stderr)
                return {"success": False, "message": f"Invalid SSID or password: {stderr.strip()}"}
            # Remove the plaintext #psk= comment line
            network_block = "\n".join(
                line for line in stdout.strip().splitlines()
                if not line.strip().startswith("#psk=")
            )
            log.info("Generated WPA network block for ssid=%r", ssid)
        else:
            # Open network — escape SSID to prevent wpa_supplicant.conf injection.
            # wpa_supplicant uses C-style escapes inside double-quoted ssid strings,
            # so we must escape backslashes and double-quotes at minimum.
            safe_open_ssid = ssid.replace("\\", "\\\\").replace('"', '\\"')
            # Reject control characters (newline, tab, etc.) that could break config
            if any(ord(c) < 0x20 for c in safe_open_ssid):
                log.error("SSID contains control characters: %r", ssid)
                return {"success": False, "message": "Invalid SSID: contains control characters"}
            network_block = f'network={{\n\tssid="{safe_open_ssid}"\n\tkey_mgmt=NONE\n}}'
            log.info("Generated open network block for ssid=%r", ssid)

        # 2. Read current config, preserve header (ctrl_interface, country, etc.)
        conf = Path(WPA_CONF)
        try:
            current = conf.read_text()
        except Exception:
            current = "ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=wheel\nupdate_config=1\ncountry=JP\n"
            log.warning("Could not read %s, using defaults", WPA_CONF)

        # Extract header (everything before first "network={")
        header_lines = []
        for line in current.splitlines():
            if line.strip().startswith("network="):
                break
            header_lines.append(line)
        header = "\n".join(header_lines).rstrip()

        # Build new config: header + new network
        new_config = f"{header}\n\n{network_block}\n"

        # 3. Remount RW, write config, restart wpa_supplicant, remount RO
        async with async_remount_rw(WPA_CONF):
            try:
                # Write config
                conf.write_text(new_config)
                log.info("Wrote wpa_supplicant config: %s", WPA_CONF)

                # Restart wpa_supplicant to pick up new config
                rc, stdout, stderr = await _run(
                    ["systemctl", "restart", "wpa_supplicant@wlan0"]
                )
                if rc != 0:
                    log.error("Failed to restart wpa_supplicant: %s %s", stdout, stderr)
                    return {"success": False, "message": f"Failed to restart WiFi service: {stderr.strip()}"}
                log.info("wpa_supplicant@wlan0 restarted")

                # 4. Wait for connection + DHCP
                await asyncio.sleep(5)
                # Try dhcpcd first, fall back to dhclient — hardcoded constants only
                rc_dhcp, _, _ = await _run(["dhcpcd", INTERFACE])
                if rc_dhcp != 0:
                    await _run(["dhclient", INTERFACE])
                await asyncio.sleep(3)

                # 5. Verify
                st = await self.status()
                if st.connected:
                    log.info("WiFi connected: ssid=%s ip=%s", st.ssid, st.ip_address)
                else:
                    log.warning("WiFi connection timeout for ssid=%r", ssid)
                return {
                    "success": st.connected,
                    "message": "Connected" if st.connected else "Connection timeout — check password",
                    "ip": st.ip_address,
                }
            except Exception as e:
                log.error("WiFi connect error: %s", e)
                return {"success": False, "message": str(e)}

    async def disconnect(self) -> dict:
        """Disconnect by removing network blocks and restarting wpa_supplicant."""
        log.info("WiFiManager.disconnect")

        conf = Path(WPA_CONF)
        try:
            current = conf.read_text()
        except Exception:
            return {"success": False, "message": "Config file not found"}

        # Keep only header, remove all network blocks
        header_lines = []
        for line in current.splitlines():
            if line.strip().startswith("network="):
                break
            header_lines.append(line)
        new_config = "\n".join(header_lines).rstrip() + "\n"

        async with async_remount_rw(WPA_CONF):
            conf.write_text(new_config)
            await _run(["systemctl", "restart", "wpa_supplicant@wlan0"])
            log.info("WiFi disconnected, config cleaned")

        return {"success": True}
