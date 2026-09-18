#!/usr/bin/env python3
"""Generate GR5526 firmware binary with Image Info header.

Appends a 48-byte Image Info header to the raw firmware .bin.
Header format (little-endian):
  0-3   magic (0x00014744 = "DG" + version 1)
  4-7   bin_len (firmware length excluding this header)
  8-11  crc32
  12-15 load_addr (flash address)
  16-19 run_addr (XIP mode = load_addr)
  20-23 field_20 (firmware type)
  24-27 field_24 (version)
  28-47 name (20 bytes ASCII, null-padded)

Usage:
    python generate_image_info.py --input raw.bin --output fw.bin \
        --load-addr 0x00240000 --name ble_app_uart_c
"""
from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

IMAGE_INFO_SIZE = 48
IMAGE_INFO_MAGIC = 0x00014744


def build_image_info(
    firmware: bytes,
    load_addr: int,
    name: str,
    run_addr: int | None = None,
    field_20: int = 0,
    field_24: int = 0,
) -> bytes:
    """Build 48-byte Image Info header."""
    if run_addr is None:
        run_addr = load_addr  # XIP mode

    crc = zlib.crc32(firmware) & 0xFFFFFFFF
    name_bytes = name.encode("ascii", errors="replace")[:20].ljust(20, b"\x00")

    header = struct.pack(
        "<IIIIIII20s",
        IMAGE_INFO_MAGIC,
        len(firmware),
        crc,
        load_addr,
        run_addr,
        field_20,
        field_24,
        name_bytes,
    )
    assert len(header) == IMAGE_INFO_SIZE, f"Header size {len(header)} != {IMAGE_INFO_SIZE}"
    return header

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate GR5526 firmware with Image Info header")
    parser.add_argument("--input", required=True, help="Raw firmware .bin path")
    parser.add_argument("--output", required=True, help="Output firmware .bin path (with Image Info)")
    parser.add_argument("--load-addr", required=True, help="Flash load address (hex, e.g. 0x00240000)")
    parser.add_argument("--name", required=True, help="Firmware name (max 20 chars)")
    parser.add_argument("--run-addr", default=None, help="Run address (default: same as load-addr)")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"[FAIL] Input file not found: {input_path}", file=sys.stderr)
        return 1

    firmware = input_path.read_bytes()
    load_addr = int(args.load_addr, 16) if args.load_addr.startswith("0x") else int(args.load_addr)
    run_addr = int(args.run_addr, 16) if args.run_addr and args.run_addr.startswith("0x") else (int(args.run_addr) if args.run_addr else None)

    header = build_image_info(firmware, load_addr, args.name, run_addr)
    output_data = firmware + header

    output_path.write_bytes(output_data)

    print(f"[PASS] Generated {output_path}")
    print(f"  Input size : {len(firmware)} bytes")
    print(f"  Output size: {len(output_data)} bytes (firmware + {IMAGE_INFO_SIZE} header)")
    print(f"  Load addr  : 0x{load_addr:08X}")
    print(f"  CRC32      : 0x{struct.unpack_from('<I', header, 8)[0]:08X}")
    print(f"  Name       : {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
