#!/usr/bin/env python3
"""Detect complete firmware layout from build artifacts.

Extracts RTT control block addresses, Image Info metadata, and derives
flash partition layout from GCC .map files and firmware binaries.
Outputs key=value pairs for Jenkins pipeline environment variable injection.

Detection sources (priority order):
  1. Image Info header (last 48 bytes of firmware .bin) - load_addr, run_addr, bin_len, crc32, name
  2. GCC .map file - _SEGGER_RTT symbol address, stack top, memory regions
  3. Derived layout - BL_END = APP_ADDR - 1, APP_END = APP_ADDR + bin_len - 1, BANK_B = APP_END + 1

Usage:
    python detect_firmware_layout.py --bl-map <path> --app-map <path> \\
        --bl-bin <path> --app-bin <path> [--output <json>]

Output key=value pairs:
    BL_RTT_ADDR, APP_RTT_ADDR          - RTT control block addresses
    BL_ADDR, BL_END                     - Bootloader flash region
    APP_ADDR, APP_END                   - App flash region
    BANK_B_ADDR, BANK_B_END            - Bank B flash region (for dual-bank OTA)
    NVDS_ADDR                           - NVDS parameter storage address
    BL_BIN_LEN, APP_BIN_LEN            - Firmware binary lengths
    BL_RUN_ADDR, APP_RUN_ADDR          - Firmware runtime addresses
    BL_FW_NAME, APP_FW_NAME            - Firmware names from Image Info
"""
from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

IMAGE_INFO_SIZE = 48
IMAGE_INFO_MAGIC = 0x00014744  # "DG" + version 1, little-endian

# GR5526 default flash layout (fallback when detection fails)
DEFAULT_LAYOUT = {
    "bl_addr": 0x00204000,
    "bl_end": 0x0023FFFF,
    "app_addr": 0x00240000,
    "app_end": 0x00297FFF,
    "bank_b_addr": 0x00298000,
    "bank_b_end": 0x002EFFFF,
    "nvds_addr": 0x002EF000,
}

# Required fields that must be detected for pipeline to proceed
# APP_RTT_ADDR is optional - debug_ota_flow.py can auto-scan RTT at runtime
REQUIRED_FIELDS = ["BL_RTT_ADDR", "BL_ADDR", "APP_ADDR"]


# ---------------------------------------------------------------------------
# Data structures (dataclass for clean, immutable-ish data holders)
# ---------------------------------------------------------------------------

@dataclass
class ImageInfo:
    """Parsed Image Info header (last 48 bytes of firmware binary)."""
    magic: int = 0
    bin_len: int = 0
    crc32: int = 0
    load_addr: int = 0
    run_addr: int = 0
    field_20: int = 0
    field_24: int = 0
    name: str = ""
    valid: bool = False

@dataclass
class MapSymbols:
    """Symbols extracted from GCC .map file."""
    rtt_addr: int | None = None
    stack_top: int | None = None
    flash_origin: int | None = None


@dataclass
class FirmwareProfile:
    """Complete profile for one firmware (bootloader or app)."""
    label: str = ""
    image_info: ImageInfo = field(default_factory=ImageInfo)
    map_symbols: MapSymbols = field(default_factory=MapSymbols)


@dataclass
class FlashLayout:
    """Derived flash partition layout."""
    bl_addr: int = 0
    bl_end: int = 0
    app_addr: int = 0
    app_end: int = 0
    bank_b_addr: int = 0
    bank_b_end: int = 0
    nvds_addr: int = 0


@dataclass
class DetectionResult:
    """Complete detection result."""
    bootloader: FirmwareProfile = field(default_factory=lambda: FirmwareProfile(label="BL"))
    app: FirmwareProfile = field(default_factory=lambda: FirmwareProfile(label="APP"))
    flash: FlashLayout = field(default_factory=FlashLayout)
    errors: list[str] = field(default_factory=list)

    def to_key_values(self) -> list[tuple[str, str]]:
        """Convert to key=value pairs for Jenkins environment injection."""
        kv: list[tuple[str, str]] = []

        # RTT addresses (from .map)
        if self.bootloader.map_symbols.rtt_addr:
            kv.append(("BL_RTT_ADDR", f"0x{self.bootloader.map_symbols.rtt_addr:08X}"))
        if self.app.map_symbols.rtt_addr:
            kv.append(("APP_RTT_ADDR", f"0x{self.app.map_symbols.rtt_addr:08X}"))

        # Flash partition layout
        kv.append(("BL_ADDR", f"0x{self.flash.bl_addr:08X}"))
        kv.append(("BL_END", f"0x{self.flash.bl_end:08X}"))
        kv.append(("APP_ADDR", f"0x{self.flash.app_addr:08X}"))
        kv.append(("APP_END", f"0x{self.flash.app_end:08X}"))
        kv.append(("BANK_B_ADDR", f"0x{self.flash.bank_b_addr:08X}"))
        kv.append(("BANK_B_END", f"0x{self.flash.bank_b_end:08X}"))
        kv.append(("NVDS_ADDR", f"0x{self.flash.nvds_addr:08X}"))

        # Firmware metadata (from Image Info)
        if self.bootloader.image_info.valid:
            kv.append(("BL_BIN_LEN", str(self.bootloader.image_info.bin_len)))
            kv.append(("BL_RUN_ADDR", f"0x{self.bootloader.image_info.run_addr:08X}"))
            kv.append(("BL_FW_NAME", self.bootloader.image_info.name))
        if self.app.image_info.valid:
            kv.append(("APP_BIN_LEN", str(self.app.image_info.bin_len)))
            kv.append(("APP_RUN_ADDR", f"0x{self.app.image_info.run_addr:08X}"))
            kv.append(("APP_FW_NAME", self.app.image_info.name))

        return kv


# ---------------------------------------------------------------------------
# .map file detectors (Strategy: each function is an interchangeable detection strategy)
# ---------------------------------------------------------------------------

def detect_rtt_from_map(map_path: str) -> int | None:
    """Extract _SEGGER_RTT control block address from GCC .map file.

    Matches lines like:  0x2000c830                _SEGGER_RTT
    """
    path = Path(map_path)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"0x([0-9a-fA-F]+)\s+_SEGGER_RTT\s*$", re.MULTILINE)
    m = pattern.search(content)
    return int(m.group(1), 16) if m else None


def detect_stack_top_from_map(map_path: str) -> int | None:
    """Extract __StackTop from .map file."""
    path = Path(map_path)
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8", errors="replace")
    pattern = re.compile(r"0x([0-9a-fA-F]+)\s+__StackTop\s*=", re.MULTILINE)
    m = pattern.search(content)
    return int(m.group(1), 16) if m else None


def detect_map_symbols(map_path: str) -> MapSymbols:
    """Run all .map detection strategies and return combined MapSymbols."""
    return MapSymbols(
        rtt_addr=detect_rtt_from_map(map_path),
        stack_top=detect_stack_top_from_map(map_path),
    )

# ---------------------------------------------------------------------------
# Image Info parser (Strategy: parse firmware binary header)
# ---------------------------------------------------------------------------

def parse_image_info(bin_path: str) -> ImageInfo:
    """Parse Image Info header from last 48 bytes of firmware binary.

    Structure (little-endian):
        0-3   magic (0x00014744 = "DG" + version 1)
        4-7   bin_len (firmware length excluding this header)
        8-11  crc32
        12-15 load_addr (flash address)
        16-19 run_addr (XIP mode = load_addr)
        20-23 field_20 (unknown, likely firmware type)
        24-27 field_24 (unknown, likely version)
        28-47 name (20 bytes ASCII, null-padded)
    """
    info = ImageInfo()
    path = Path(bin_path)
    if not path.exists():
        return info

    data = path.read_bytes()
    if len(data) < IMAGE_INFO_SIZE:
        return info

    header = data[-IMAGE_INFO_SIZE:]

    try:
        info.magic = struct.unpack_from("<I", header, 0)[0]
        if info.magic != IMAGE_INFO_MAGIC:
            return info  # Not a valid Image Info header

        info.bin_len = struct.unpack_from("<I", header, 4)[0]
        info.crc32 = struct.unpack_from("<I", header, 8)[0]
        info.load_addr = struct.unpack_from("<I", header, 12)[0]
        info.run_addr = struct.unpack_from("<I", header, 16)[0]
        info.field_20 = struct.unpack_from("<I", header, 20)[0]
        info.field_24 = struct.unpack_from("<I", header, 24)[0]

        name_bytes = header[28:48]
        info.name = name_bytes.split(b"\x00")[0].decode("ascii", errors="replace")
        info.valid = True
    except struct.error:
        pass

    return info


# ---------------------------------------------------------------------------
# Flash layout derivation (Template Method: define derivation skeleton)
# ---------------------------------------------------------------------------

def derive_flash_layout(bl: FirmwareProfile, app: FirmwareProfile) -> FlashLayout:
    """Derive complete flash partition layout from detected firmware info.

    Priority for each field:
        1. Image Info load_addr (most authoritative - actual firmware header)
        2. .map file flash_origin (link-time configuration)
        3. Default fallback (GR5526 standard layout)
    """
    layout = FlashLayout()

    # Bootloader start: Image Info > .map > default
    if bl.image_info.valid and bl.image_info.load_addr:
        layout.bl_addr = bl.image_info.load_addr
    elif bl.map_symbols.flash_origin:
        layout.bl_addr = bl.map_symbols.flash_origin
    else:
        layout.bl_addr = DEFAULT_LAYOUT["bl_addr"]

    # App start: Image Info > .map > default
    if app.image_info.valid and app.image_info.load_addr:
        layout.app_addr = app.image_info.load_addr
    elif app.map_symbols.flash_origin:
        layout.app_addr = app.map_symbols.flash_origin
    else:
        layout.app_addr = DEFAULT_LAYOUT["app_addr"]

    # Bootloader end = app start - 1 (contiguous layout)
    if layout.app_addr > layout.bl_addr:
        layout.bl_end = layout.app_addr - 1
    else:
        layout.bl_end = DEFAULT_LAYOUT["bl_end"]

    # App end = app start + bin_len - 1 (from Image Info)
    if app.image_info.valid and app.image_info.bin_len > 0:
        layout.app_end = layout.app_addr + app.image_info.bin_len - 1
    else:
        layout.app_end = DEFAULT_LAYOUT["app_end"]

    # Bank B start = app end + 1
    layout.bank_b_addr = layout.app_end + 1

    # Bank B end = default (before NVDS)
    layout.bank_b_end = DEFAULT_LAYOUT["bank_b_end"]

    # NVDS address (fixed by SDK, last sector of flash)
    layout.nvds_addr = DEFAULT_LAYOUT["nvds_addr"]

    return layout


# ---------------------------------------------------------------------------
# Main orchestration (Facade: single entry point for all detection)
# ---------------------------------------------------------------------------

def detect_all(
    bl_map: str,
    app_map: str,
    bl_bin: str | None = None,
    app_bin: str | None = None,
) -> DetectionResult:
    """Run all detection strategies and return complete DetectionResult."""
    result = DetectionResult()

    # 1. Detect from .map files
    print(">>> [1/3] Detecting symbols from .map files...")
    result.bootloader.map_symbols = detect_map_symbols(bl_map)
    result.app.map_symbols = detect_map_symbols(app_map)

    bl_rtt = result.bootloader.map_symbols.rtt_addr
    app_rtt = result.app.map_symbols.rtt_addr
    print(f"    BL  RTT: 0x{bl_rtt:08X}" if bl_rtt else "    BL  RTT: NOT FOUND")
    print(f"    APP RTT: 0x{app_rtt:08X}" if app_rtt else "    APP RTT: NOT FOUND")

    if not bl_rtt:
        result.errors.append(f"BL RTT address not found in {bl_map}")
    if not app_rtt:
        result.errors.append(f"APP RTT address not found in {app_map}")

    # 2. Parse Image Info from firmware binaries
    print(">>> [2/3] Parsing Image Info headers from firmware binaries...")
    if bl_bin:
        result.bootloader.image_info = parse_image_info(bl_bin)
        ii = result.bootloader.image_info
        if ii.valid:
            print(f"    BL  Image Info: load=0x{ii.load_addr:08X} run=0x{ii.run_addr:08X} "
                  f"len={ii.bin_len} name='{ii.name}'")
        else:
            print("    BL  Image Info: NOT FOUND or INVALID")
            result.errors.append(f"BL Image Info not found in {bl_bin}")
    else:
        print("    BL  Image Info: skipped (no --bl-bin provided)")

    if app_bin:
        result.app.image_info = parse_image_info(app_bin)
        ii = result.app.image_info
        if ii.valid:
            print(f"    APP Image Info: load=0x{ii.load_addr:08X} run=0x{ii.run_addr:08X} "
                  f"len={ii.bin_len} name='{ii.name}'")
        else:
            print("    APP Image Info: NOT FOUND or INVALID")
            result.errors.append(f"APP Image Info not found in {app_bin}")
    else:
        print("    APP Image Info: skipped (no --app-bin provided)")

    # 3. Derive flash layout
    print(">>> [3/3] Deriving flash partition layout...")
    result.flash = derive_flash_layout(result.bootloader, result.app)
    f = result.flash
    print(f"    BL      : 0x{f.bl_addr:08X} - 0x{f.bl_end:08X} "
          f"({(f.bl_end - f.bl_addr + 1) // 1024} KB)")
    print(f"    APP     : 0x{f.app_addr:08X} - 0x{f.app_end:08X} "
          f"({(f.app_end - f.app_addr + 1) // 1024} KB)")
    print(f"    BANK_B  : 0x{f.bank_b_addr:08X} - 0x{f.bank_b_end:08X}")
    print(f"    NVDS    : 0x{f.nvds_addr:08X}")

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect complete firmware layout from build artifacts"
    )
    parser.add_argument("--bl-map", required=True, help="Bootloader GCC .map file path")
    parser.add_argument("--app-map", required=True, help="App GCC .map file path")
    parser.add_argument("--bl-bin", default=None, help="Bootloader firmware .bin path")
    parser.add_argument("--app-bin", default=None, help="App firmware .bin path")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args(argv)

    # Run all detection
    result = detect_all(args.bl_map, args.app_map, args.bl_bin, args.app_bin)

    # Output key=value pairs
    print("\n=== KEY=VALUE OUTPUT (for Jenkins env injection) ===")
    kv_pairs = result.to_key_values()
    for key, value in kv_pairs:
        print(f"{key}={value}")

    # Optional JSON output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(asdict(result), f, indent=2, default=str)
        print(f"\nJSON output written to: {args.output}")

    # Validate required fields
    found_keys = {k for k, _ in kv_pairs}
    missing = [k for k in REQUIRED_FIELDS if k not in found_keys]
    if missing:
        print(f"\n[FAIL] Missing required fields: {', '.join(missing)}", file=sys.stderr)
        if result.errors:
            print("Errors:", file=sys.stderr)
            for e in result.errors:
                print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"\n[PASS] All {len(REQUIRED_FIELDS)} required fields detected successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
