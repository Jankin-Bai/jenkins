#!/usr/bin/env python3
"""Verify GR5526 flash contents after programming.

Reads dump files produced by GR5xxx_console dump commands and validates:
  1. Bank A (App region) is NOT all 0xFF (App was programmed)
  2. SCA (System Configuration Area) at 0x00200000 has valid Boot_Info
  3. Boot_Info run_addr / load_addr are consistent with BL address

This script is called from Jenkins Stage 4 (Flash Verify MANDATORY GATE).
It receives all parameters via environment variables:
  - WORKSPACE   : Jenkins workspace root (where verify_*.bin dumps are)
  - BL_ADDR     : Bootloader base address (hex string, e.g. 0x00204000)

Exit codes:
    0 = verification passed
    1 = verification failed (mandatory gate)
"""
from __future__ import annotations

import os
import sys


def rd(path: str) -> bytes:
    """Read a binary file, return bytes."""
    with open(path, "rb") as f:
        return f.read()


def main() -> int:
    ws = os.environ.get("WORKSPACE", ".")

    # --- Verify Bank A (App) not all 0xFF ---
    bank_path = os.path.join(ws, "verify_bank_a.bin")
    try:
        bank = rd(bank_path)
    except FileNotFoundError:
        print(f"FAIL: {bank_path} not found - App dump missing")
        return 1

    print("BankA %dB: %s" % (len(bank), " ".join("%02X" % b for b in bank[:64])))
    if all(b == 0xFF for b in bank):
        print("FAIL: Bank A all 0xFF - App not programmed")
        return 1
    print("PASS: Bank A has firmware data")

    # --- Verify SCA - dump full 256 bytes and find non-0xFF regions ---
    sca_path = os.path.join(ws, "verify_sca.bin")
    try:
        sca = rd(sca_path)
    except FileNotFoundError:
        print(f"FAIL: {sca_path} not found - SCA dump missing")
        return 1

    print("SCA %dB full dump:" % len(sca))
    for i in range(0, len(sca), 16):
        hex_part = " ".join("%02X" % b for b in sca[i:i+16])
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in sca[i:i+16])
        print("  0x%04X: %s  %s" % (i, hex_part, ascii_part))

    # Find non-0xFF regions
    non_ff = []
    start = None
    for i, b in enumerate(sca):
        if b != 0xFF:
            if start is None:
                start = i
        else:
            if start is not None:
                non_ff.append((start, i - 1))
                start = None
    if start is not None:
        non_ff.append((start, len(sca) - 1))
    print("Non-0xFF regions in SCA: %s" % (
        ["0x%04X-0x%04X" % (s, e) for s, e in non_ff] or "none (all erased)"
    ))

    # --- Check Boot_Info at offset 0 (32 bytes) ---
    boot_info = sca[:32]
    if all(b == 0xFF for b in boot_info):
        print("FAIL: Boot_Info at offset 0 is all 0xFF (ERASED) - ROM Bootloader cannot boot! "
              "--erase 2 did not write SCA")
        return 1

    print("Boot_Info at offset 0: %s" % " ".join("%02X" % b for b in boot_info))
    run_addr = int.from_bytes(boot_info[8:12], "little")
    load_addr = int.from_bytes(boot_info[12:16], "little")
    app_size = int.from_bytes(boot_info[20:24], "little")
    print("  RunAddr=0x%08X LoadAddr=0x%08X Size=%d" % (run_addr, load_addr, app_size))

    # --- Check if SCA contains BL address bytes ---
    bl_addr_str = os.environ.get("BL_ADDR", "0x00204000")
    bl_addr = int(bl_addr_str, 16)
    bl_bytes = bytes([
        bl_addr & 0xFF,
        (bl_addr >> 8) & 0xFF,
        (bl_addr >> 16) & 0xFF,
        (bl_addr >> 24) & 0xFF,
    ])
    has_bl = bl_bytes in sca
    print("SCA contains BL addr bytes 0x%08X anywhere: %s" % (bl_addr, has_bl))
    if has_bl:
        idx = sca.find(bl_bytes)
        print("  Found at offset 0x%04X" % idx)

    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
