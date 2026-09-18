#!/usr/bin/env python3
"""Generate and verify firmware metadata for CI traceability.

This tool ensures that every flashed firmware can be traced back to:
  - The exact git commit and branch it was built from
  - The SDK versions used
  - The chip and build type

Usage:
    # Generate metadata (called after build stage):
    python firmware_metadata.py generate \
        --chip GR5526 --build-number 123 \
        --bootloader-sdk "1.0.3" --app-sdk "1.0.4" \
        --app-image app_fw.bin --build-type normal \
        --workspace "D:\...\w4" \
        --output artifacts/firmware_metadata.json

    # Verify metadata (called before flash stage):
    python firmware_metadata.py verify \
        --metadata artifacts/firmware_metadata.json \
        --workspace "D:\...\w4"

Exit codes:
    0 = success
    1 = verification failed (git_commit mismatch)
    2 = generate error (missing input)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def git_command(args: list[str], cwd: str) -> str:
    """Run a git command and return stdout (stripped). Exit 1 on failure."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[firmware_metadata] git {' '.join(args)} failed: {result.stderr.strip()}",
                  file=sys.stderr)
            sys.exit(1)
        return result.stdout.strip()
    except FileNotFoundError:
        print("[firmware_metadata] git not found in PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print("[firmware_metadata] git command timed out", file=sys.stderr)
        sys.exit(1)


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate firmware_metadata.json from current build context."""
    workspace = args.workspace or os.getcwd()

    # Collect git info
    git_commit = git_command(["rev-parse", "HEAD"], workspace)
    git_branch = git_command(["rev-parse", "--abbrev-ref", "HEAD"], workspace)

    # Build metadata dict
    metadata = {
        "chip": args.chip,
        "build_number": args.build_number,
        "git_commit": git_commit,
        "git_branch": git_branch,
        "bootloader_sdk": args.bootloader_sdk,
        "app_sdk": args.app_sdk,
        "app_image": args.app_image,
        "build_type": args.build_type,
    }

    # Write output
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"[PASS] firmware_metadata.json written to {out_path}")
    print(f"  chip         : {metadata['chip']}")
    print(f"  build_number : {metadata['build_number']}")
    print(f"  git_commit   : {metadata['git_commit']}")
    print(f"  git_branch   : {metadata['git_branch']}")
    print(f"  bootloader_sdk: {metadata['bootloader_sdk']}")
    print(f"  app_sdk      : {metadata['app_sdk']}")
    print(f"  app_image    : {metadata['app_image']}")
    print(f"  build_type   : {metadata['build_type']}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify that metadata git_commit matches current working tree HEAD."""
    workspace = args.workspace or os.getcwd()

    meta_path = Path(args.metadata)
    if not meta_path.exists():
        print(f"[FAIL] Metadata file not found: {meta_path}", file=sys.stderr)
        return 1

    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    expected_commit = metadata.get("git_commit", "")
    if not expected_commit:
        print("[FAIL] metadata has no git_commit field", file=sys.stderr)
        return 1

    current_commit = git_command(["rev-parse", "HEAD"], workspace)

    if expected_commit != current_commit:
        print(f"[FAIL] Git commit mismatch!", file=sys.stderr)
        print(f"  Metadata commit: {expected_commit}", file=sys.stderr)
        print(f"  Current HEAD   : {current_commit}", file=sys.stderr)
        print(f"  This firmware was NOT built from the current codebase.", file=sys.stderr)
        return 1

    print(f"[PASS] Metadata verified: git_commit={current_commit}")
    print(f"  chip        : {metadata.get('chip')}")
    print(f"  build_number: {metadata.get('build_number')}")
    print(f"  git_branch  : {metadata.get('git_branch')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate and verify firmware metadata for CI traceability"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate subcommand
    p_gen = sub.add_parser("generate", help="Generate firmware_metadata.json")
    p_gen.add_argument("--chip", required=True, help="Chip name (e.g. GR5526)")
    p_gen.add_argument("--build-number", required=True, help="Jenkins build number")
    p_gen.add_argument("--bootloader-sdk", required=True, help="Bootloader SDK version")
    p_gen.add_argument("--app-sdk", required=True, help="App SDK version")
    p_gen.add_argument("--app-image", required=True, help="App firmware image filename")
    p_gen.add_argument("--build-type", default="normal", help="Build type label")
    p_gen.add_argument("--workspace", default=None, help="Workspace root for git commands")
    p_gen.add_argument("--output", required=True, help="Output JSON file path")

    # verify subcommand
    p_ver = sub.add_parser("verify", help="Verify firmware metadata against current HEAD")
    p_ver.add_argument("--metadata", required=True, help="Path to firmware_metadata.json")
    p_ver.add_argument("--workspace", default=None, help="Workspace root for git commands")

    args = parser.parse_args(argv)

    if args.command == "generate":
        return cmd_generate(args)
    elif args.command == "verify":
        return cmd_verify(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
