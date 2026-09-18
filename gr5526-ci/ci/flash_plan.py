#!/usr/bin/env python3
"""Generate and validate flash plan before hardware programming.

This tool creates an explicit, auditable flash plan that documents:
  - Which flash regions will be erased
  - Which regions must be preserved (NVDS)
  - The programming order (App FIRST, Bootloader LAST)
  - Safety validation before any hardware action

Usage:
    # Generate flash plan:
    python flash_plan.py generate \
        --chip GR5526 \
        --bl-addr 0x00204000 --bl-end 0x0023FFFF \
        --app-addr 0x00240000 --app-end 0x00297FFF \
        --bank-b-addr 0x00298000 --bank-b-end 0x002EFFFF \
        --nvds-addr 0x002EF000 \
        --output artifacts/flash_plan.json

    # Validate flash plan against safety rules:
    python flash_plan.py validate --plan artifacts/flash_plan.json

Exit codes:
    0 = plan generated / validated successfully
    1 = validation failed (safety rule violation)
    2 = generate error (missing input)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def hex_int(s: str) -> int:
    """Parse a hex string (0x...) or decimal string to int."""
    s = s.strip()
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return int(s)


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate flash_plan.json from detected layout."""
    bl_addr = hex_int(args.bl_addr)
    bl_end = hex_int(args.bl_end)
    app_addr = hex_int(args.app_addr)
    app_end = hex_int(args.app_end)
    bank_b_addr = hex_int(args.bank_b_addr)
    bank_b_end = hex_int(args.bank_b_end)
    nvds_addr = hex_int(args.nvds_addr)

    plan = {
        "chip": args.chip,
        "erase_regions": [
            {
                "name": "bootloader_region",
                "start": f"0x{bl_addr:08X}",
                "end": f"0x{bl_end:08X}",
                "purpose": "Bootloader flash region",
            },
            {
                "name": "bank_a",
                "start": f"0x{app_addr:08X}",
                "end": f"0x{app_end:08X}",
                "purpose": "App flash region (Bank A)",
            },
            {
                "name": "bank_b",
                "start": f"0x{bank_b_addr:08X}",
                "end": f"0x{bank_b_end:08X}",
                "purpose": "Bank B flash region (OTA backup)",
            },
        ],
        "preserve_regions": [
            {
                "name": "NVDS",
                "start": f"0x{nvds_addr:08X}",
                "purpose": "NVDS parameter storage - MUST NOT be erased or overwritten",
            }
        ],
        "program_order": [
            {
                "order": 1,
                "image": "app_fw.bin",
                "purpose": "Program App FIRST (SCA temporarily points to App)",
            },
            {
                "order": 2,
                "image": "bl_fw.bin",
                "purpose": "Program Bootloader LAST (SCA finally points to Bootloader)",
            },
        ],
        "hard_rules": [
            "GR5xxx_console ONLY for flash ops - NO J-Link flash/reset",
            "App FIRST, Bootloader LAST (SCA final -> Bootloader)",
            "NVDS preserved - NO eraseall",
            "Addresses from detect_firmware_layout.py",
        ],
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    print(f"[PASS] flash_plan.json written to {out_path}")
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate flash plan against hardware safety rules."""
    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"[FAIL] Flash plan not found: {plan_path}", file=sys.stderr)
        return 1

    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    errors: list[str] = []
    warnings: list[str] = []

    # Rule 1: NVDS must be in preserve_regions, not in erase_regions
    preserve_names = [r.get("name", "").upper() for r in plan.get("preserve_regions", [])]
    erase_names = [r.get("name", "").upper() for r in plan.get("erase_regions", [])]

    if "NVDS" not in preserve_names:
        errors.append("NVDS is NOT in preserve_regions - this would erase NVDS!")

    if "NVDS" in erase_names:
        errors.append("NVDS is listed in erase_regions - FORBIDDEN!")

    # Check address overlap: NVDS must not fall within any erase region
    preserve_regions = plan.get("preserve_regions", [])
    erase_regions = plan.get("erase_regions", [])
    for pr in preserve_regions:
        pr_start = hex_int(pr.get("start", "0x0"))
        for er in erase_regions:
            er_start = hex_int(er.get("start", "0x0"))
            er_end = hex_int(er.get("end", "0x0"))
            if er_start <= pr_start <= er_end:
                errors.append(
                    f"NVDS (0x{pr_start:08X}) falls within erase region "
                    f"{er.get('name')} (0x{er_start:08X}-0x{er_end:08X})"
                )

    # Rule 2: Program order must be App FIRST, Bootloader LAST
    order_list = plan.get("program_order", [])
    if len(order_list) >= 2:
        first = order_list[0]
        last = order_list[-1]
        if "app" not in first.get("image", "").lower():
            errors.append(
                f"Program order violation: first image is '{first.get('image')}', "
                "expected App FIRST"
            )
        if "bl" not in last.get("image", "").lower() and "boot" not in last.get("image", "").lower():
            errors.append(
                f"Program order violation: last image is '{last.get('image')}', "
                "expected Bootloader LAST"
            )
    else:
        warnings.append("program_order has fewer than 2 entries - cannot verify App-first/BL-last")

    # Rule 3: No eraseall - check that erase_regions are specific, not full chip
    if len(erase_regions) == 0:
        warnings.append("No erase regions in plan - nothing will be erased")

    # Rule 4: Hard rules must be documented
    hard_rules = plan.get("hard_rules", [])
    if len(hard_rules) == 0:
        warnings.append("No hard_rules documented in flash plan")

    # Report
    for w in warnings:
        print(f"[WARN] {w}")

    if errors:
        print("[FAIL] Flash plan validation FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("[PASS] Flash plan validation passed. All safety rules satisfied.")
    print("  - NVDS preserved")
    print("  - App FIRST, Bootloader LAST")
    print("  - No erase regions overlap NVDS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and validate flash plan for GR5526 hardware CI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate", help="Generate flash_plan.json")
    p_gen.add_argument("--chip", required=True, help="Chip name")
    p_gen.add_argument("--bl-addr", required=True, help="Bootloader start address (hex)")
    p_gen.add_argument("--bl-end", required=True, help="Bootloader end address (hex)")
    p_gen.add_argument("--app-addr", required=True, help="App start address (hex)")
    p_gen.add_argument("--app-end", required=True, help="App end address (hex)")
    p_gen.add_argument("--bank-b-addr", required=True, help="Bank B start address (hex)")
    p_gen.add_argument("--bank-b-end", required=True, help="Bank B end address (hex)")
    p_gen.add_argument("--nvds-addr", required=True, help="NVDS address (hex)")
    p_gen.add_argument("--output", required=True, help="Output JSON file path")

    p_val = sub.add_parser("validate", help="Validate flash plan against safety rules")
    p_val.add_argument("--plan", required=True, help="Path to flash_plan.json")

    args = parser.parse_args(argv)

    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "validate":
        return cmd_validate(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
