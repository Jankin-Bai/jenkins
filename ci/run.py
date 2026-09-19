#!/usr/bin/env python3
"""ci/run.py —— GR5526 CI 总入口（规则20）。

Jenkinsfile 只调用本脚本的子命令，不包含任何业务逻辑：
    python ci/run.py preflight
    python ci/run.py build-bl
    python ci/run.py build-app
    python ci/run.py metadata
    python ci/run.py detect-layout
    python ci/run.py verify-metadata
    python ci/run.py validate-plan
    python ci/run.py locate-images
    python ci/run.py erase
    python ci/run.py program-app
    python ci/run.py program-bl
    python ci/run.py verify-flash
    python ci/run.py reset
    python ci/run.py rtt
    python ci/run.py collect-result

环境变量由 Jenkins environment{} 注入：
    CI_ROOT, VENV_PY, TOOLS, CI_DIR, ARTIFACTS, CHIP
    BL_GCC, APP_GCC, BL_SDK, APP_SDK, GR_CONSOLE
    BL_PROJECT_PATH, APP_PROJECT_PATH
    DRY_RUN, SKIP_BUILD, SKIP_FLASH, ALLOW_PREBUILT_FIRMWARE, ALLOW_LAYOUT_FALLBACK
    BL_KEYWORD, APP_KEYWORD, BUILD_NUMBER, BUILD_URL, JOB_NAME

产物（全部写到 ARTIFACTS 目录，规则6/19）：
    hardware_context.json   preflight 产出（J-Link 信息、节点、芯片）
    flash_plan.json         detect-layout / locate-images 产出（地址表、镜像路径）
    firmware_metadata.json  metadata 产出（git_commit、SDK 版本、build_type）
    bl_build.json           build-bl 产出（status、image 路径）
    app_build.json          build-app 产出
    test_result.json        collect-result 产出
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# 让 ci/flash/gr_console.py 可导入
sys.path.insert(0, str(Path(__file__).parent))
from flash.gr_console import GrConsole, from_env  # noqa: E402


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"env {name} not set")
    return v


def is_dry_run() -> bool:
    return env("DRY_RUN", "false").lower() in ("1", "true", "yes")


def artifact_path(name: str) -> Path:
    p = Path(env("ARTIFACTS"))
    p.mkdir(parents=True, exist_ok=True)
    return p / name


def load_json(name: str) -> dict:
    p = artifact_path(name)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_json(name: str, data: dict) -> None:
    p = artifact_path(name)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[artifact] wrote {p}")


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd)
    if check and proc.returncode != 0:
        raise SystemExit(proc.returncode)
    return proc


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------
def cmd_preflight(_args) -> None:
    """Stage 1.2: 工具/SDK/Makefile 存在性检查 + py_compile + J-Link 检测。"""
    # 调试打印：确认 Jenkins 参数确实注入了环境变量
    print(f"[preflight] DRY_RUN env = {os.environ.get('DRY_RUN', '<MISSING>')!r}")
    print(f"[preflight] BL_GCC  env = {os.environ.get('BL_GCC', '<MISSING>')!r}")
    print(f"[preflight] APP_GCC env = {os.environ.get('APP_GCC', '<MISSING>')!r}")

    # TODO: 1) 检查 GR_CONSOLE / arm-none-eabi-gcc / mingw32-make 存在
    # TODO: 2) 检查 BL_GCC/Makefile, APP_GCC/Makefile, BL_SDK, APP_SDK
    # TODO: 3) 检查 tools/*.py 与 ci/flash_plan.py 存在
    # TODO: 4) py_compile 所有 .py
    # TODO: 5) 调 tools/jlink_detect.py —— 改造后应直接写
    #        artifacts/hardware_context.json，而不是 stdout key=value
    #        （见 REFACTORING_NOTES.md 第1条）
    print("[preflight] TODO: implement existence checks + py_compile + jlink_detect")
    ctx = {
        "chip": env("CHIP"),
        "agent_label": "gr5526-hw",
        "jlink": {
            # TODO: 从 jlink_detect.py 输出读入
            "path": "", "serial": "", "idx": "", "usb_id": "",
        },
    }
    save_json("hardware_context.json", ctx)


def cmd_build_bl(_args) -> None:
    """Stage 2.1: 编译 bootloader + generate bl_fw.bin。"""
    # DRY_RUN 检查必须在读取任何 env 之前，避免缺变量时直接崩
    if is_dry_run():
        out_bin = env("CI_ROOT") + "\\bl_fw.bin"
        print("[build-bl][DRY-RUN] would: make clean && make && grConsole generate")
        save_json("bl_build.json", {"status": "dry-run", "image": out_bin})
        return

    bl_gcc = Path(env("BL_GCC"))
    out_bin = env("CI_ROOT") + "\\bl_fw.bin"
    console = from_env()
    # TODO: cd BL_GCC && mingw32-make clean && mingw32-make
    # TODO: 校验 out/app_bootloader.bin 存在
    # TODO: console.generate_image(bl_gcc/out/app_bootloader.bin, out_bin, "0x00200000", 1024, 1)
    print("[build-bl] TODO: implement make + grConsole generate")
    save_json("bl_build.json", {"status": "success", "image": out_bin})


def cmd_build_app(_args) -> None:
    """Stage 2.2: 编译 APP（含 response file fallback）+ generate app_fw.bin。"""
    if is_dry_run():
        print("[build-app][DRY-RUN] would: make SDK_ROOT=... clean && make")
        save_json("app_build.json", {"status": "dry-run", "image": env("CI_ROOT") + "\\app_fw.bin"})
        return
    # 调 scripts/build_app.bat（已抽出）。退出码: 0=成功 2=prebuilt 1=失败
    proc = run(["cmd", "/c", os.path.join(env("CI_ROOT"), "scripts", "build_app.bat"),
                ], check=False)
    if proc.returncode == 0:
        # TODO: 调 tools/generate_image_info.py 生成 app_fw.bin --load-addr 0x00240000
        status = "success"
    elif proc.returncode == 2:
        if env("ALLOW_PREBUILT_FIRMWARE", "false").lower() == "true":
            status = "prebuilt-firmware"
        else:
            print("[build-app] FAILED and ALLOW_PREBUILT_FIRMWARE=false", file=sys.stderr)
            raise SystemExit(1)
    else:
        raise SystemExit(proc.returncode)
    save_json("app_build.json", {"status": status,
                                 "image": env("CI_ROOT") + "\\app_fw.bin"})


def cmd_metadata(_args) -> None:
    """Stage 3: firmware_metadata.py generate。"""
    bl = load_json("bl_build.json")
    app = load_json("app_build.json")
    build_type = f"{bl.get('status', 'unknown')}-APP-{app.get('status', 'unknown')}"
    # TODO: 调 tools/firmware_metadata.py generate
    #   --chip CHIP --build-number BUILD_NUMBER
    #   --bootloader-sdk 1.0.3 --app-sdk 1.0.4
    #   --app-image app_fw.bin --build-type <build_type>
    #   --workspace CI_ROOT --output ARTIFACTS/firmware_metadata.json
    print(f"[metadata] TODO: firmware_metadata.py generate (build_type={build_type})")


def cmd_detect_layout(_args) -> None:
    """Stage 4.1: detect_firmware_layout.py —— 直接写 flash_plan.json。

    改造后不再 stdout key=value，不再由 Jenkinsfile 解析。
    fallback 地址表、BANK_B_END clamp 全部在这里完成。
    """
    if is_dry_run():
        plan = {
            "bl":    {"addr": "0x00204000", "end": "0x0023FFFF"},
            "app":   {"addr": "0x00240000", "end": "0x00297FFF"},
            "bank_b":{"addr": "0x00298000", "end": "0x002EEFFF"},
            "nvds":  "0x002EF000",
            "rtt":   {"bl": "0x2000C830", "app": "0x2000D000"},
            "fallback": True,
        }
        save_json("flash_plan.json", plan)
        return
    # TODO: 调 tools/detect_firmware_layout.py
    #   --bl-map BL_GCC/out/lst/app_bootloader.map
    #   --bl-bin CI_ROOT/bl_fw.bin --app-bin CI_ROOT/app_fw.bin
    #   [--app-map APP_GCC/out/lst/ble_app_uart_c.elf]
    # 脚本直接写 flash_plan.json（含 clamp 后地址）。
    # 若检测失败且 ALLOW_LAYOUT_FALLBACK=true，写 fallback；否则 exit 1。
    print("[detect-layout] TODO: detect_firmware_layout.py -> flash_plan.json")


def cmd_verify_metadata(_args) -> None:
    """Stage 4.2: firmware_metadata.py verify（git_commit 对齐）。"""
    meta = artifact_path("firmware_metadata.json")
    if not meta.exists():
        print("[verify-metadata] no metadata (build skipped) — skip")
        return
    # TODO: 调 tools/firmware_metadata.py verify --metadata <meta> --workspace CI_ROOT
    print("[verify-metadata] TODO")


def cmd_validate_plan(_args) -> None:
    """Stage 4.3: flash_plan.py validate。"""
    # TODO: 调 ci/flash_plan.py validate --plan ARTIFACTS/flash_plan.json
    print("[validate-plan] TODO")


def cmd_locate_images(_args) -> None:
    """Stage 4.4: 定位 bl_fw.bin / app_fw.bin，写回 flash_plan.json。"""
    plan = load_json("flash_plan.json")
    if is_dry_run():
        # DRY_RUN：填占位路径，不真找
        plan.setdefault("bl_image", env("CI_ROOT") + "\\bl_fw.bin")
        plan.setdefault("app_image", env("CI_ROOT") + "\\app_fw.bin")
        save_json("flash_plan.json", plan)
        print("[locate-images][DRY-RUN] placeholder image paths written")
        return
    # TODO: 优先 CI_ROOT/bl_fw.bin、CI_ROOT/app_fw.bin；
    # 找不到再在 BL_GCC / APP_GCC 下 dir /b /s *.bin 找。
    # 找到后写 plan["bl_image"], plan["app_image"]，save_json。
    print("[locate-images] TODO: locate bl_fw.bin / app_fw.bin")


def cmd_erase(_args) -> None:
    """Stage 4.6: 擦 BL / Bank A / Bank B（NVDS 保留）。"""
    if is_dry_run():
        print("[erase][DRY-RUN] would: erase BL + BankA + BankB (NVDS preserved)")
        return
    plan = load_json("flash_plan.json")
    ctx = load_json("hardware_context.json")
    console = from_env()
    jlink_idx = ctx.get("jlink", {}).get("idx", "0")
    chip = env("CHIP")
    console.erase_region(plan["bl"]["addr"],    plan["bl"]["end"],    chip, jlink_idx)
    console.erase_region(plan["app"]["addr"],   plan["app"]["end"],   chip, jlink_idx)
    console.erase_region(plan["bank_b"]["addr"], plan["bank_b"]["end"], chip, jlink_idx)
    print("[erase] BL + BankA + BankB erased; NVDS preserved")


def cmd_program_app(_args) -> None:
    """Stage 4.7: APP FIRST。"""
    if is_dry_run():
        print("[program-app][DRY-RUN] would: program APP image FIRST")
        return
    plan = load_json("flash_plan.json")
    console = from_env()
    ctx = load_json("hardware_context.json")
    image = Path(plan["app_image"])
    if not image.exists():
        raise SystemExit(f"APP image not found: {image}")
    console.program(image, env("CHIP"), ctx["jlink"]["idx"])
    print("[program-app] APP programmed FIRST")


def cmd_program_bl(_args) -> None:
    """Stage 4.8: Bootloader LAST（SCA 最终指向 BL）。"""
    if is_dry_run():
        print("[program-bl][DRY-RUN] would: program Bootloader LAST")
        return
    plan = load_json("flash_plan.json")
    console = from_env()
    ctx = load_json("hardware_context.json")
    image = Path(plan["bl_image"])
    if not image.exists():
        raise SystemExit(f"BL image not found: {image}")
    console.program(image, env("CHIP"), ctx["jlink"]["idx"])
    print("[program-bl] Bootloader programmed LAST; SCA final -> BL")


def cmd_verify_flash(_args) -> None:
    """Stage 4.9: dump Bank A + SCA，调 verify_flash.py 比对。"""
    if is_dry_run():
        print("[verify-flash][DRY-RUN] skip dump+verify")
        return
    plan = load_json("flash_plan.json")
    ctx = load_json("hardware_context.json")
    console = from_env()
    ws = Path(env("WORKSPACE"))
    console.dump(plan["app"]["addr"], 64, ws / "verify_bank_a.bin", ctx["jlink"]["idx"])
    console.dump("0x00200000", 256, ws / "verify_sca.bin", ctx["jlink"]["idx"])
    # TODO: 调 tools/verify_flash.py（读 WORKSPACE + flash_plan.json）
    print("[verify-flash] TODO: verify_flash.py")


def cmd_reset(_args) -> None:
    """Stage 4.10: GR5xxx_console reset（不用 J-Link）。"""
    if is_dry_run():
        print("[reset][DRY-RUN] would: reset device via GR5xxx_console")
        return
    console = from_env()
    console.reset(1, 0)
    print("[reset] device reset via GR5xxx_console")


def cmd_rtt(_args) -> None:
    """Stage 5: RTT 诊断。失败由 Jenkinsfile catchError 标 UNSTABLE。"""
    plan = load_json("flash_plan.json")
    ctx = load_json("hardware_context.json")
    bl_rtt = plan.get("rtt", {}).get("bl", "0x2000C830")
    app_rtt = plan.get("rtt", {}).get("app", "0x2000D000")
    cmd = [
        env("VENV_PY"), "-u", os.path.join(env("TOOLS"), "test_rtt_with_jump.py"),
        "--bl-rtt-addr", bl_rtt, "--app-rtt-addr", app_rtt,
        "--jlink-serial", ctx["jlink"]["serial"],
        "--bl-timeout", "8", "--jump-timeout", "20",
        "--output", str(Path(env("WORKSPACE")) / "rtt_result.json"),
    ]
    if env("BL_KEYWORD"):
        cmd += ["--bl-keyword", env("BL_KEYWORD")]
    if env("APP_KEYWORD"):
        cmd += ["--app-keyword", env("APP_KEYWORD")]
    run(cmd)


def cmd_collect_result(_args) -> None:
    """post.always: 聚合各 artifact 生成 test_result.json。"""
    plan = load_json("flash_plan.json")
    meta = load_json("firmware_metadata.json")
    hw = load_json("hardware_context.json")
    bl = load_json("bl_build.json")
    app = load_json("app_build.json")
    dry = is_dry_run()
    flash_status = "SKIPPED" if env("SKIP_FLASH", "false") == "true" else ("DRY_RUN" if dry else "PASS")
    result = {
        "job": env("JOB_NAME", "gr5526-ci"),
        "build_number": int(env("BUILD_NUMBER", "0")),
        "build_url": env("BUILD_URL", ""),
        "dry_run": dry,
        "chip": env("CHIP"),
        "jlink_serial": hw.get("jlink", {}).get("serial", ""),
        "bl_image": bl.get("image", plan.get("bl_image", "")),
        "app_image": app.get("image", plan.get("app_image", "")),
        "flash": flash_status,
        "layout": {
            "bl": plan.get("bl"), "app": plan.get("app"),
            "bank_b": plan.get("bank_b"), "nvds": plan.get("nvds"),
        },
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    save_json("test_result.json", result)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(prog="ci/run.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name, fn in [
        ("preflight", cmd_preflight),
        ("build-bl", cmd_build_bl),
        ("build-app", cmd_build_app),
        ("metadata", cmd_metadata),
        ("detect-layout", cmd_detect_layout),
        ("verify-metadata", cmd_verify_metadata),
        ("validate-plan", cmd_validate_plan),
        ("locate-images", cmd_locate_images),
        ("erase", cmd_erase),
        ("program-app", cmd_program_app),
        ("program-bl", cmd_program_bl),
        ("verify-flash", cmd_verify_flash),
        ("reset", cmd_reset),
        ("rtt", cmd_rtt),
        ("collect-result", cmd_collect_result),
    ]:
        sub.add_parser(name).set_defaults(func=fn)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
