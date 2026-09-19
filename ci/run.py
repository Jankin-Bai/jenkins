#!/usr/bin/env python3
"""ci/run.py - GR5526 CI entry point (rule 20).

Architecture: Facade pattern - CLI dispatch only, business logic in submodules.
    Jenkinsfile -> ci/run.py -> ci/config.py + ci/artifacts.py -> flash/gr_console.py

Usage:
    python ci/run.py preflight
    python ci/run.py build-bl
    python ci/run.py build-app
    python ci/run.py plan
    python ci/run.py validate
    python ci/run.py erase
    python ci/run.py program-bl
    python ci/run.py program-app
    python ci/run.py verify
    python ci/run.py collect-result
"""
from __future__ import annotations
import argparse
import functools
import logging
import subprocess
import sys
from pathlib import Path

from config import CIConfig
from artifacts import ArtifactRepository

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decorator: DRY_RUN guard (eliminates repeated if is_dry_run())
# ---------------------------------------------------------------------------
def dry_run_guard(message: str):
    """Stage function decorator: print message and return in DRY_RUN, skip real logic."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(config: CIConfig, artifacts: ArtifactRepository, *args, **kwargs):
            if config.is_dry_run:
                print(f"[DRY-RUN] {message}")
                return
            return func(config, artifacts, *args, **kwargs)
        return wrapper
    return decorator


def run_cmd(cmd: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Execute a shell command, print it, optionally check return code."""
    print(f"$ {cmd}", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, shell=True)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


def _which(tool: str) -> bool:
    return subprocess.run(f"where {tool}", shell=True,
                          stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_preflight(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 1.2: toolchain + SDK + Makefile existence checks."""
    print(f"[preflight] DRY_RUN={config.dry_run}  BUILD_MODE={config.build_mode}  BOARD={config.board_type}")

    errors = []
    for tool in ["arm-none-eabi-gcc", "mingw32-make"]:
        if not _which(tool):
            errors.append(f"tool not in PATH: {tool}")
    if not config.gr_console.exists():
        errors.append(f"GR5xxx_console not found: {config.gr_console}")
    for label, path in [("BL", config.bl_gcc / "Makefile"),
                         ("APP", config.app_gcc / "Makefile")]:
        if not path.exists():
            errors.append(f"{label} Makefile not found: {path}")
    if not config.sdk_dir.exists():
        errors.append(f"SDK not found: {config.sdk_dir}")

    if errors:
        for e in errors:
            print(f"[preflight][FAIL] {e}", file=sys.stderr)
        raise SystemExit(1)

    print("[preflight] all checks passed")
    artifacts.save("hardware_context.json", {
        "chip": config.chip,
        "agent_label": config.agent_label,
        "project_root": str(config.project_root),
    })


@dry_run_guard("would: make clean && make -j4 in bootloader/GCC")
def cmd_build_bl(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 2.1: compile Bootloader."""
    if config.skip_build:
        print("[build-bl] SKIP_BUILD=true - using prebuilt bin")
        return

    run_cmd("make clean", cwd=config.bl_gcc, check=False)
    run_cmd("make -j4", cwd=config.bl_gcc)

    bl_bin = config.bl_gcc / "out" / "app_bootloader.bin"
    if not bl_bin.exists():
        raise SystemExit(f"BL build failed: {bl_bin} not found")
    print(f"[build-bl] OK: {bl_bin} ({bl_bin.stat().st_size} bytes)")
    artifacts.save("bl_build.json", {
        "status": "success",
        "image": str(bl_bin),
        "size": bl_bin.stat().st_size,
    })


@dry_run_guard("would: make clean && make {flags} -j4 in ble_app_uart_c/GCC")
def cmd_build_app(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 2.2: compile APP (with conditional build flags)."""
    if config.skip_build:
        print("[build-app] SKIP_BUILD=true - using prebuilt bin")
        return

    flags = config.app_build_flags
    run_cmd("make clean", cwd=config.app_gcc, check=False)
    run_cmd(f"make {flags} -j4", cwd=config.app_gcc)

    app_bin = config.app_gcc / "out" / "ble_app_uart_c.bin"
    if not app_bin.exists():
        raise SystemExit(f"APP build failed: {app_bin} not found")
    print(f"[build-app] OK: {app_bin} ({app_bin.stat().st_size} bytes)")
    artifacts.save("app_build.json", {
        "status": "success",
        "image": str(app_bin),
        "size": app_bin.stat().st_size,
        "flags": flags,
    })


def cmd_plan(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 4: write flash_plan.json (address layout is known for GR5526)."""
    plan = {
        "bl":     {"addr": "0x00204000", "end": "0x0023FFFF"},
        "app":    {"addr": "0x00240000", "end": "0x002BFFFF"},
        "bank_b": {"addr": "0x002C0000", "end": "0x0033FFFF"},
        "nvds":   "0x00340000",
        "rtt":    {"bl": "0x2000C830", "app": "0x2000D000"},
        "layout_source": "hardcoded (GR5526 dual-bank)",
    }
    artifacts.save("flash_plan.json", plan)
    print("[plan] flash layout written")


def cmd_validate(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 5: check bin files exist and have content."""
    bl = artifacts.load("bl_build.json")
    app = artifacts.load("app_build.json")

    for label, data in [("BL", bl), ("APP", app)]:
        img = data.get("image", "")
        if img and not Path(img).exists():
            raise SystemExit(f"{label} image missing: {img}")
        if not img and not config.skip_build:
            raise SystemExit(f"{label} build skipped but no prebuilt image")

    print("[validate] all images present")


@dry_run_guard("would: GR5xxx_console erase BL + BankA + BankB")
def cmd_erase(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 7.1: erase (NVDS preserved)."""
    if config.skip_erase:
        print("[erase] SKIP_ERASE=true")
        return
    # TODO: call gr_console.erase_region for BL / BankA / BankB
    print("[erase] TODO: GR5xxx_console eraseall / erase_region")


@dry_run_guard("would: program bootloader @0x00204000")
def cmd_program_bl(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 7.2: flash BL."""
    if config.skip_flash:
        print("[program-bl] SKIP_FLASH=true")
        return
    # TODO: gr_console.generate + gr_console.program
    print("[program-bl] TODO: GR5xxx_console generate + program")


@dry_run_guard("would: program app @0x00240000")
def cmd_program_app(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 7.3: flash APP."""
    if config.skip_flash:
        print("[program-app] SKIP_FLASH=true")
        return
    # TODO: gr_console.generate + gr_console.program
    print("[program-app] TODO: GR5xxx_console generate + program")


@dry_run_guard("would: verify flash")
def cmd_verify(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """Stage 8: verify."""
    # TODO: gr_console.dump + verify
    print("[verify] TODO")


def cmd_collect_result(config: CIConfig, artifacts: ArtifactRepository) -> None:
    """post.always: aggregate results."""
    bl = artifacts.load("bl_build.json")
    app = artifacts.load("app_build.json")
    result = {
        "job": "gr5526-ci-v2",
        "dry_run": config.dry_run,
        "build_mode": config.build_mode,
        "board_type": config.board_type,
        "bl_image": bl.get("image", ""),
        "app_image": app.get("image", ""),
        "flash": "SKIPPED" if config.skip_flash else ("DRY_RUN" if config.dry_run else "DONE"),
    }
    artifacts.save("test_result.json", result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
COMMANDS = {
    "preflight":     cmd_preflight,
    "build-bl":      cmd_build_bl,
    "build-app":     cmd_build_app,
    "plan":          cmd_plan,
    "validate":      cmd_validate,
    "erase":         cmd_erase,
    "program-bl":    cmd_program_bl,
    "program-app":   cmd_program_app,
    "verify":        cmd_verify,
    "collect-result": cmd_collect_result,
}


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(prog="ci/run.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in COMMANDS:
        sub.add_parser(name)
    args = parser.parse_args()

    config = CIConfig.from_env()
    artifacts = ArtifactRepository(config.artifacts_dir)
    COMMANDS[args.cmd](config, artifacts)


if __name__ == "__main__":
    main()
