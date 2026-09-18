#!/usr/bin/env python3
"""GR5526 RTT test with BL->App jump handling.

Resets the device, reads bootloader RTT logs, waits for the bootloader
to jump to the app, then reads app RTT logs. Handles the RTT control
block address switch automatically.

Usage:
    python test_rtt_with_jump.py \\
        --bl-rtt-addr 0x2000C830 \\
        --app-rtt-addr 0x2000D000 \\
        --jlink-serial 670024969 \\
        --bl-keyword "bootloader" \\
        --app-keyword "app" \\
        --bl-timeout 5 \\
        --jump-timeout 15 \\
        --output rtt_test_result.json

Exit code 0 = both tests pass, 1 = any test fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# RTT control block offsets
RTT_MAGIC_OFFSET = 0
RTT_MAGIC_LEN = 16
RTT_UP_BUF_ADDR_OFFSET = 24
RTT_UP_BUF_SIZE_OFFSET = 28
RTT_UP_WR_OFFSET = 32
RTT_UP_RD_OFFSET = 36

RTT_MAGIC = b"SEGGER RTT"

# Flash region boundaries (for PC-based jump detection)
BL_REGION_START = 0x00204000
BL_REGION_END = 0x00240000
APP_REGION_START = 0x00240000
RAM_REGION_START = 0x20000000
RAM_REGION_END = 0x20020000

def connect_jlink(serial: int | None = None):
    """Connect to J-Link and return the JLink object."""
    import pylink
    j = pylink.JLink()
    if serial:
        j.open(serial_no=serial)
    else:
        j.open()
    j.set_tif(pylink.enums.JLinkInterfaces.SWD)
    j.connect("Cortex-M4", speed=4000)
    return j

def read_rtt_output(j, rtt_addr: int, max_read: int = 8192) -> str:
    """Read RTT up-channel 0 output from a given control block address.

    Returns the decoded text, or empty string if RTT not initialized.
    """
    try:
        # Read RTT control block (48 bytes)
        cb = bytes(j.memory_read8(rtt_addr, 48))
        if cb[:10] != RTT_MAGIC:
            return ""

        buf_addr = int.from_bytes(cb[RTT_UP_BUF_ADDR_OFFSET:RTT_UP_BUF_ADDR_OFFSET + 4], "little")
        buf_size = int.from_bytes(cb[RTT_UP_BUF_SIZE_OFFSET:RTT_UP_BUF_SIZE_OFFSET + 4], "little")
        wr_off = int.from_bytes(cb[RTT_UP_WR_OFFSET:RTT_UP_WR_OFFSET + 4], "little")
        rd_off = int.from_bytes(cb[RTT_UP_RD_OFFSET:RTT_UP_RD_OFFSET + 4], "little")

        if not buf_addr or buf_size == 0 or wr_off == 0:
            return ""

        # Read from rd_off to wr_off (handle wrap-around)
        if wr_off >= rd_off:
            length = wr_off - rd_off
        else:
            length = buf_size - rd_off + wr_off

        length = min(length, max_read)
        if length == 0:
            return ""

        # Read in chunks to handle wrap-around
        data = bytearray()
        pos = rd_off
        remaining = length
        while remaining > 0:
            chunk_size = min(remaining, buf_size - pos)
            chunk = bytes(j.memory_read8(buf_addr + pos, chunk_size))
            data.extend(chunk)
            pos = (pos + chunk_size) % buf_size
            remaining -= chunk_size

        return data.decode("ascii", errors="replace")
    except Exception as e:
        return f"[RTT read error: {e}]"

def read_pc(j) -> int:
    """Read current PC (requires halted core)."""
    j.halt()
    pc = j.register_read(15)
    j.restart()
    return pc

def detect_region(pc: int) -> str:
    """Classify PC into a region."""
    if pc < 0x00100000:
        return "ROM"
    elif BL_REGION_START <= pc < BL_REGION_END:
        return "BL"
    elif pc >= APP_REGION_START:
        return "APP"
    elif RAM_REGION_START <= pc < RAM_REGION_END:
        return "RAM"
    else:
        return "UNKNOWN"

def wait_for_region(j, target: str, timeout: int, interval: float = 0.5) -> tuple[bool, int, str]:
    """Wait until PC is in the target region. Returns (success, pc, region)."""
    deadline = time.time() + timeout
    last_pc = 0
    last_region = "UNKNOWN"
    while time.time() < deadline:
        pc = read_pc(j)
        region = detect_region(pc)
        last_pc = pc
        last_region = region
        if region == target:
            return True, pc, region
        time.sleep(interval)
    return False, last_pc, last_region

def run_test(args) -> dict:
    """Run the full RTT test sequence. Returns result dict."""
    result = {
        "bl": {"pass": False, "rtt": "", "pc": 0, "region": "", "error": ""},
        "app": {"pass": False, "rtt": "", "pc": 0, "region": "", "error": ""},
        "jump_detected": False,
    }

    j = None
    try:
        j = connect_jlink(args.jlink_serial)
        print(f"[INFO] J-Link connected, core=0x{j.core_id():08X}")

        # --- Reset is done externally via GR5xxx_console (Stage 3.6) ---
        # DO NOT use J-Link reset (j.restart) - it can leave the core in ROM.
        # The device is already reset and running when this script starts.
        print("[INFO] Device already reset via GR5xxx_console. Connecting J-Link for RTT read...")
        time.sleep(0.5)

        # --- Phase 1: Bootloader RTT ---
        print(f"[INFO] Waiting for bootloader (timeout={args.bl_timeout}s)...")
        bl_ok, bl_pc, bl_region = wait_for_region(j, "BL", args.bl_timeout)
        result["bl"]["pc"] = bl_pc
        result["bl"]["region"] = bl_region
        print(f"[INFO] BL phase: PC=0x{bl_pc:08X} region={bl_region}")

        # Read BL RTT (retry a few times for RTT init)
        bl_rtt = ""
        for attempt in range(3):
            bl_rtt = read_rtt_output(j, args.bl_rtt_addr)
            if bl_rtt and "RTT read error" not in bl_rtt:
                break
            time.sleep(1)
        result["bl"]["rtt"] = bl_rtt
        print(f"[INFO] BL RTT output ({len(bl_rtt)} bytes):")
        if bl_rtt:
            print(bl_rtt[:2000])
            if len(bl_rtt) > 2000:
                print(f"... ({len(bl_rtt) - 2000} more bytes)")

        # Check BL success
        if bl_rtt and args.bl_keyword.lower() in bl_rtt.lower():
            result["bl"]["pass"] = True
            print(f"[PASS] Bootloader RTT contains keyword '{args.bl_keyword}'")
        elif bl_rtt and len(bl_rtt) > 10:
            # If no keyword specified or keyword not found but there's output,
            # consider it a soft pass if keyword is empty
            if not args.bl_keyword:
                result["bl"]["pass"] = True
                print("[PASS] Bootloader RTT has output (no keyword specified)")
            else:
                print(f"[WARN] Bootloader RTT output exists but keyword '{args.bl_keyword}' not found")
        else:
            print("[FAIL] Bootloader RTT no output or not initialized")

        # --- Phase 2: Wait for jump to App ---
        print(f"[INFO] Waiting for BL->App jump (timeout={args.jump_timeout}s)...")
        jump_ok, jump_pc, jump_region = wait_for_region(j, "APP", args.jump_timeout, interval=1.0)
        result["jump_detected"] = jump_ok
        print(f"[INFO] Jump detection: PC=0x{jump_pc:08X} region={jump_region}")

        if not jump_ok:
            print("[WARN] Jump to APP not detected via PC. Will still try to read APP RTT.")

        # Give app time to initialize RTT
        time.sleep(2)

        # --- Phase 3: App RTT ---
        app_rtt = ""
        for attempt in range(3):
            app_rtt = read_rtt_output(j, args.app_rtt_addr)
            if app_rtt and "RTT read error" not in app_rtt:
                break
            time.sleep(1)
        result["app"]["rtt"] = app_rtt
        result["app"]["pc"] = read_pc(j)
        result["app"]["region"] = detect_region(result["app"]["pc"])
        print(f"[INFO] APP RTT output ({len(app_rtt)} bytes):")
        if app_rtt:
            print(app_rtt[:2000])
            if len(app_rtt) > 2000:
                print(f"... ({len(app_rtt) - 2000} more bytes)")

        # Check APP success
        if app_rtt and args.app_keyword.lower() in app_rtt.lower():
            result["app"]["pass"] = True
            print(f"[PASS] App RTT contains keyword '{args.app_keyword}'")
        elif app_rtt and len(app_rtt) > 10:
            if not args.app_keyword:
                result["app"]["pass"] = True
                print("[PASS] App RTT has output (no keyword specified)")
            else:
                print(f"[WARN] App RTT output exists but keyword '{args.app_keyword}' not found")
        else:
            print("[FAIL] App RTT no output or not initialized")

    except Exception as e:
        print(f"[ERROR] Test failed: {e}", file=sys.stderr)
        result["bl"]["error"] = str(e)
        result["app"]["error"] = str(e)
    finally:
        if j:
            try:
                j.restart()
                j.close()
            except Exception:
                pass

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GR5526 RTT test with BL->App jump handling")
    parser.add_argument("--bl-rtt-addr", required=True, help="Bootloader RTT control block address (hex)")
    parser.add_argument("--app-rtt-addr", required=True, help="App RTT control block address (hex)")
    parser.add_argument("--jlink-serial", type=int, default=None, help="J-Link serial number")
    parser.add_argument("--bl-keyword", default="", help="Keyword to look for in BL RTT output (empty=any output)")
    parser.add_argument("--app-keyword", default="", help="Keyword to look for in APP RTT output (empty=any output)")
    parser.add_argument("--bl-timeout", type=int, default=8, help="Seconds to wait for bootloader to start")
    parser.add_argument("--jump-timeout", type=int, default=20, help="Seconds to wait for BL->App jump")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args(argv)

    # Parse hex addresses
    args.bl_rtt_addr = int(args.bl_rtt_addr, 16) if args.bl_rtt_addr.startswith("0x") else int(args.bl_rtt_addr)
    args.app_rtt_addr = int(args.app_rtt_addr, 16) if args.app_rtt_addr.startswith("0x") else int(args.app_rtt_addr)

    print("=" * 60)
    print("GR5526 RTT Test (BL -> App jump handling)")
    print(f"  BL RTT addr : 0x{args.bl_rtt_addr:08X}")
    print(f"  APP RTT addr: 0x{args.app_rtt_addr:08X}")
    print(f"  BL keyword  : '{args.bl_keyword}'")
    print(f"  APP keyword : '{args.app_keyword}'")
    print("=" * 60)

    result = run_test(args)

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print(f"  Bootloader: {'PASS' if result['bl']['pass'] else 'FAIL'} "
          f"(region={result['bl']['region']}, rtt_len={len(result['bl']['rtt'])})")
    print(f"  App        : {'PASS' if result['app']['pass'] else 'FAIL'} "
          f"(region={result['app']['region']}, rtt_len={len(result['app']['rtt'])})")
    print(f"  Jump detected: {result['jump_detected']}")
    print("=" * 60)

    # Write JSON output
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"[INFO] Result written to {output_path}")

    if result["bl"]["pass"] and result["app"]["pass"]:
        print("[PASS] All RTT tests passed.")
        return 0
    else:
        print("[FAIL] Some RTT tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
