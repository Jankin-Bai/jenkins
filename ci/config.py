#!/usr/bin/env python3
"""ci/config.py - 集中读取 CI 配置，派生工程路径和编译 flags。

遵循规则 5/19：env 只描述执行环境，artifact 描述动态状态。
本模块只负责"从 env 读一次，后面全用对象"。
"""
from __future__ import annotations
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if v is None:
        raise RuntimeError(f"env {name} not set")
    return v


@dataclass(frozen=True)
class CIConfig:
    """CI 执行环境配置（从环境变量一次性读取，不可变）。"""
    # 工作区
    ci_root: Path
    venv_py: Path
    tools_dir: Path
    artifacts_dir: Path
    workspace: Path

    # 芯片与硬件
    chip: str
    agent_label: str

    # 工程根目录（用户参数）
    project_root: Path

    # 派生路径
    bl_gcc: Path = field(init=False)
    app_gcc: Path = field(init=False)
    sdk_dir: Path = field(init=False)
    gr_console: Path = field(init=False)

    # 构建参数
    dry_run: bool
    skip_build: bool
    skip_flash: bool
    skip_erase: bool
    wait_human: bool
    allow_prebuilt: bool
    allow_layout_fallback: bool

    # 编译 flags 来源
    build_mode: str       # release / debug
    board_type: str      # TK_PAD / TK_1_1 / TK
    cli_port: bool

    # RTT 关键字
    bl_keyword: str
    app_keyword: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "bl_gcc", self.project_root / "bootloader" / "GCC")
        object.__setattr__(self, "app_gcc", self.project_root / "ble_app_uart_c" / "GCC")
        object.__setattr__(self, "sdk_dir", self.project_root / "GR5526_SDK_V1.0.4")
        object.__setattr__(self, "gr_console",
                           Path(r"D:\Program Files (x86)\Goodix\GProgrammer\GR5xxx_console.exe"))

    @property
    def app_build_flags(self) -> str:
        """根据 Jenkins 参数组合 APP 编译 flags。"""
        parts = []
        if self.board_type == "TK_PAD":
            parts.append("USE_BOARD_TK_PAD=1")
        elif self.board_type == "TK_1_1":
            parts.append("USE_BOARD_TK_1_1=1")
        elif self.board_type == "TK":
            parts.append("USE_BOARD_TK=1")
        if self.build_mode == "release":
            parts.append("FW_release=1")
        else:
            parts.append("FW_release=0")
            parts.append("DEBUG_IDLE=1")
        if self.cli_port:
            parts.append("CLI_PORT=1")
        flags = " ".join(parts)
        log.info("APP build flags: %s", flags)
        return flags

    @property
    def is_dry_run(self) -> bool:
        return self.dry_run

    @classmethod
    def from_env(cls) -> "CIConfig":
        """从环境变量构造配置对象。"""
        dry = _env("DRY_RUN", "false").lower() in ("1", "true", "yes")
        return cls(
            ci_root=Path(_env("CI_ROOT")),
            venv_py=Path(_env("VENV_PY")),
            tools_dir=Path(_env("TOOLS")),
            artifacts_dir=Path(_env("ARTIFACTS")),
            workspace=Path(_env("WORKSPACE")),
            chip=_env("CHIP", "gr5526"),
            agent_label="gr5526-hw",
            project_root=Path(_env("PROJECT_ROOT")),
            dry_run=dry,
            skip_build=_env("SKIP_BUILD", "false").lower() == "true",
            skip_flash=_env("SKIP_FLASH", "false").lower() == "true",
            skip_erase=_env("SKIP_ERASE", "false").lower() == "true",
            wait_human=_env("WAIT_FOR_HUMAN_CONFIRMATION", "false").lower() == "true",
            allow_prebuilt=_env("ALLOW_PREBUILT_FIRMWARE", "false").lower() == "true",
            allow_layout_fallback=_env("ALLOW_LAYOUT_FALLBACK", "false").lower() == "true",
            build_mode=_env("BUILD_MODE", "release"),
            board_type=_env("BOARD_TYPE", "TK_PAD"),
            cli_port=_env("CLI_PORT", "true").lower() == "true",
            bl_keyword=_env("BL_KEYWORD", ""),
            app_keyword=_env("APP_KEYWORD", ""),
        )
