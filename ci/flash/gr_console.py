"""GR5xxx_console 统一封装（规则9：硬件副作用单一入口）。

所有 eraseFlash / program / dump / reset / generate 都必须经过这里。
集中处理：DRY_RUN、日志、错误码检查、参数拼接。
"""
from __future__ import annotations
import os
import shlex
import subprocess
import sys
from pathlib import Path


class GrConsoleError(RuntimeError):
    pass


class GrConsole:
    def __init__(self, exe: str, dry_run: bool = False):
        self.exe = exe
        self.dry_run = dry_run

    def _run(self, args: list[str]) -> None:
        """执行 GR5xxx_console。失败抛 GrConsoleError。"""
        cmd = [self.exe, *args]
        pretty = " ".join(shlex.quote(a) for a in cmd)
        if self.dry_run:
            print(f"[DRY-RUN] GR5xxx_console: {pretty}")
            return
        print(f"[GR5526-CI] {pretty}", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.stdout:
            print(proc.stdout, end="")
        if proc.returncode != 0:
            if proc.stderr:
                print(proc.stderr, file=sys.stderr, end="")
            raise GrConsoleError(f"GR5xxx_console failed (rc={proc.returncode}): {pretty}")

    # ---- 业务动作 -------------------------------------------------------

    def generate_image(self, in_bin: Path, out_bin: Path, load_addr: str, size: int, flag: int = 1) -> None:
        self._run(["generate", str(in_bin), str(out_bin), load_addr, str(size), str(flag)])

    def erase_region(self, start: str, end: str, chip: str, jlink_idx: str) -> None:
        self._run(["eraseFlash", "--start", start, "--end", end,
                   "--chip", chip, "--jlink", jlink_idx])

    def program(self, image: Path, chip: str, jlink_idx: str, erase_mode: int = 2) -> None:
        # --erase 2: 擦 SCA/bootinfo 并重写 SCA
        self._run(["program", "--chip", chip, "--file", str(image),
                   "--erase", str(erase_mode), "--run", "false",
                   "--jlink", jlink_idx])

    def dump(self, addr: str, length: int, out_path: Path, jlink_idx: str) -> None:
        self._run(["dump", addr, str(length), str(out_path), jlink_idx])

    def reset(self, mode: int = 1, delay: int = 0) -> None:
        self._run(["reset", str(mode), str(delay)])


def from_env() -> GrConsole:
    """从环境变量构造（CI_ROOT / GR_CONSOLE / DRY_RUN）。"""
    exe = os.environ["GR_CONSOLE"]
    dry = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")
    if not Path(exe).exists() and not dry:
        raise GrConsoleError(f"GR5xxx_console not found: {exe}")
    return GrConsole(exe, dry_run=dry)
