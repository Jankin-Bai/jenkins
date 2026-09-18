#!/usr/bin/env python3
r"""J-Link auto-detection for OTA pipeline.

Probes three values at runtime, no hardcoding:
  1. JLINK_PATH    - full path to JLink.exe (registry -> PATH -> common dirs)
  2. JLINK_SERIAL  - first connected J-Link serial number (via pylink)
  3. JLINK_USB_ID  - Windows PnP device instance ID (derived from serial)

Output format (key=value, one per line) for Jenkins to parse:
    JLINK_PATH=C:\...\JLink.exe
    JLINK_SERIAL=670024969
    JLINK_USB_ID=USB\VID_1366&PID_0105\000670024969

Exit code 0 = all detected, 1 = any missing.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# SEGGER USB identifiers (constant, not user-specific)
SEGGER_VID = "VID_1366"
JLINK_PID = "PID_0105"


def find_jlink_exe() -> str | None:
    """Locate JLink.exe via registry, then PATH, then common directories."""
    # 1. Registry: HKLM\SOFTWARE\SEGGER\J-Link\InstallPath
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\SEGGER\J-Link") as key:
            install_path, _ = winreg.QueryValueEx(key, "InstallPath")
            candidate = os.path.join(install_path, "JLink.exe")
            if os.path.isfile(candidate):
                print(f"[detect] JLINK_PATH from registry: {candidate}", file=sys.stderr)
                return candidate
    except (FileNotFoundError, OSError):
        pass

    # 2. PATH
    found = shutil.which("JLink.exe")
    if found:
        print(f"[detect] JLINK_PATH from PATH: {found}", file=sys.stderr)
        return found

    # 3. Common install directories
    common_roots = [
        r"C:\Program Files\SEGGER",
        r"C:\Program Files (x86)\SEGGER",
        r"D:\Program Files\SEGGER",
        r"D:\Program Files (x86)\SEGGER",
    ]
    for root in common_roots:
        if not os.path.isdir(root):
            continue
        for entry in os.listdir(root):
            if entry.lower().startswith("jlink"):
                candidate = os.path.join(root, entry, "JLink.exe")
                if os.path.isfile(candidate):
                    print(f"[detect] JLINK_PATH from scan: {candidate}", file=sys.stderr)
                    return candidate

    return None


def find_jlink_serials() -> list[int]:
    """Enumerate connected J-Link probes via pylink. Returns serial numbers."""
    try:
        import pylink
    except ImportError:
        print("[detect] pylink not installed - cannot enumerate J-Link probes", file=sys.stderr)
        return []

    j = pylink.JLink()
    try:
        count = j.num_connected_emulators()
        if count == 0:
            return []
        emus = j.connected_emulators()
        serials = [emu.SerialNumber for emu in emus]
        print(f"[detect] Found {count} J-Link probe(s): S/N={serials}", file=sys.stderr)
        return serials
    finally:
        j.close()


def build_usb_id(serial: int) -> str:
    r"""Derive Windows PnP device instance ID from J-Link serial number.

    Format: USB\VID_1366&PID_0105\<12-digit zero-padded serial>
    """
    return f"USB\\{SEGGER_VID}&{JLINK_PID}\\{serial:012d}"

def main() -> int:
    print("=" * 60, file=sys.stderr)
    print("J-Link Auto-Detection", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    errors: list[str] = []

    # 1. JLink.exe path
    jlink_path = find_jlink_exe()
    if not jlink_path:
        errors.append("JLINK_PATH not found (registry/PATH/scan all failed)")
    else:
        print(f"JLINK_PATH={jlink_path}")

    # 2. J-Link serial number
    serials = find_jlink_serials()
    if not serials:
        errors.append("JLINK_SERIAL not found (no J-Link probe connected)")
        jlink_serial = None
        usb_id = None
        jlink_idx = None
    else:
        jlink_serial = serials[0]
        jlink_idx = 0  # first enumerated probe = index 0
        print(f"JLINK_SERIAL={jlink_serial}")
        print(f"JLINK_IDX={jlink_idx}")

        # 3. USB device ID (derived from serial)
        usb_id = build_usb_id(jlink_serial)
        print(f"JLINK_USB_ID={usb_id}")

    print("=" * 60, file=sys.stderr)
    if errors:
        print("[FAIL] Auto-detection failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print("[fix] Check: 1) J-Link software installed, 2) J-Link USB plugged in, 3) drivers loaded", file=sys.stderr)
        return 1

    print("[PASS] All J-Link parameters detected", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
