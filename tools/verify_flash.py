#!/usr/bin/env python3
"""Verify GR5526 flash contents after programming.

Reads dump files produced by GR5xxx_console dump commands and validates:
  1. Bank A (App region) is NOT all 0xFF (App was programmed)
  2. SCA (System Configuration Area) at 0x00200000 contains a valid
     ``dfu_image_info_t`` entry (Goodix image-info table).

GR5526 SCA layout (from platform/include/gr5xx_dfu.h +
components/libraries/app_bootloader/bootloader_boot_vendor.c):

  SCA + 0x00 : dfu_boot_info_t at SCA_BOOT_INFO_ADDR (often erased / 0xFF in
               the two-image App-first / BL-last flow; NOT the boot gate here).
  SCA + 0x40 : SCA_IMG_INFO_ADDR -- first ``dfu_image_info_t`` table entry:
                 uint16 pattern   // == 0x4744 (bytes "44 47" little-endian)
                 uint16 version
                 dfu_boot_info_t boot_info (24 bytes)
                   uint32 bin_size
                   uint32 check_sum
                   uint32 load_addr
                   uint32 run_addr
                   uint32 xip_cmd/flags
                 uint8  comments[12]

The boot gate is therefore the image-info *pattern* 0x4744, not the raw bytes
at SCA+0. If no 0x4744 pattern exists anywhere in the dump the SCA is truly
erased and the ROM/secondary bootloader cannot boot.

This script is called from Jenkins Stage 4 (Flash Verify MANDATORY GATE).
It receives all parameters via environment variables:
  - WORKSPACE   : Jenkins workspace root (where verify_*.bin dumps are)
  - BL_ADDR     : Bootloader base address (hex string, e.g. 0x00204000)

Exit codes:
    0 = verification passed
    1 = verification failed (mandatory gate)
"""
from __future__ import annotations

import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="[verify_flash] %(levelname)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("verify_flash")

# Goodix dfu_image_info_t.pattern = 0x4744 ("DG" little-endian: bytes 44 47)
IMG_INFO_PATTERN = 0x4744
PATTERN_BYTES = bytes([0x44, 0x47])
# dfu_image_info_t field offsets (relative to the pattern location P):
OFF_VERSION = 0x02          # uint16
OFF_BOOT_INFO = 0x04        # start of dfu_boot_info_t
OFF_BIN_SIZE = 0x00         # u32, rel boot_info
OFF_CHECK_SUM = 0x04        # u32, rel boot_info
OFF_LOAD_ADDR = 0x08        # u32, rel boot_info
OFF_RUN_ADDR = 0x0C         # u32, rel boot_info
OFF_XIP_FLAGS = 0x10        # u32, rel boot_info
OFF_COMMENTS = 0x1C         # uint8[12], rel image_info (= P + 0x1C)


def rd(path: str) -> bytes:
    """Read a binary file, return bytes."""
    with open(path, "rb") as f:
        return f.read()


def u32_le(b: bytes, off: int) -> int:
    """Read a little-endian uint32 from b at off."""
    return int.from_bytes(b[off:off + 4], "little")


def main() -> int:
    ws = os.environ.get("WORKSPACE", ".")

    # --- Verify Bank A (App) not all 0xFF ---
    bank_path = os.path.join(ws, "verify_bank_a.bin")
    try:
        bank = rd(bank_path)
    except FileNotFoundError:
        log.error("%s not found - App dump missing", bank_path)
        return 1

    print("BankA %dB: %s" % (len(bank), " ".join("%02X" % b for b in bank[:64])))
    if all(b == 0xFF for b in bank):
        log.error("Bank A all 0xFF - App not programmed")
        return 1
    log.info("Bank A has firmware data")

    # --- Verify SCA - dump full content and locate image-info pattern ---
    sca_path = os.path.join(ws, "verify_sca.bin")
    try:
        sca = rd(sca_path)
    except FileNotFoundError:
        log.error("%s not found - SCA dump missing", sca_path)
        return 1

    print("SCA %dB full dump:" % len(sca))
    for i in range(0, len(sca), 16):
        hex_part = " ".join("%02X" % b for b in sca[i:i + 16])
        ascii_part = "".join(
            chr(b) if 32 <= b < 127 else "." for b in sca[i:i + 16]
        )
        print("  0x%04X: %s  %s" % (i, hex_part, ascii_part))

    # Find non-0xFF regions (diagnostic)
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

    # --- Locate the Goodix image-info pattern (0x4744 = "44 47") ---
    pat_off = sca.find(PATTERN_BYTES)
    if pat_off < 0:
        log.error(
            "SCA contains no image-info pattern 0x4744 ('44 47') anywhere. "
            "SCA is truly erased - ROM bootloader cannot boot."
        )
        return 1

    # Parse dfu_image_info_t relative to the found pattern.
    version = int.from_bytes(sca[pat_off + OFF_VERSION:pat_off + OFF_VERSION + 2], "little")
    bi = pat_off + OFF_BOOT_INFO
    bin_size = u32_le(sca, bi + OFF_BIN_SIZE)
    check_sum = u32_le(sca, bi + OFF_CHECK_SUM)
    load_addr = u32_le(sca, bi + OFF_LOAD_ADDR)
    run_addr = u32_le(sca, bi + OFF_RUN_ADDR)
    xip_flags = u32_le(sca, bi + OFF_XIP_FLAGS)
    comments = bytes(sca[pat_off + OFF_COMMENTS:pat_off + OFF_COMMENTS + 12])
    comments_str = comments.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    print("Found image_info pattern 0x4744 at SCA+0x%04X" % pat_off)
    print("  version     = 0x%04X" % version)
    print("  bin_size     = 0x%08X (%d bytes)" % (bin_size, bin_size))
    print("  check_sum    = 0x%08X" % check_sum)
    print("  load_addr   = 0x%08X" % load_addr)
    print("  run_addr    = 0x%08X" % run_addr)
    print("  xip/flags   = 0x%08X" % xip_flags)
    print("  comments     = %r" % comments_str)

    # --- Validate load/run address matches the expected BL address ---
    bl_addr_str = os.environ.get("BL_ADDR", "0x00204000")
    bl_addr = int(bl_addr_str, 16)

    if run_addr != bl_addr:
        log.error(
            "SCA run_addr 0x%08X != BL_ADDR 0x%08X - SCA points to wrong image",
            run_addr, bl_addr,
        )
        return 1
    if load_addr != bl_addr:
        log.error(
            "SCA load_addr 0x%08X != BL_ADDR 0x%08X - SCA points to wrong image",
            load_addr, bl_addr,
        )
        return 1
    if bin_size == 0 or bin_size > 0x100000:
        log.error("SCA bin_size 0x%08X looks invalid", bin_size)
        return 1

    print("VERIFY OK: SCA image-info valid, SCA -> 0x%08X (BL)" % bl_addr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
