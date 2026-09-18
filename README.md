# gr5526-ci

GR5526 芯片 **编译 → 烧录 → 测试** 闭环 CI/CD 流水线。

## 架构

```
Jenkins SCM (Git)
    │
    ├── Jenkinsfile              # 流水线定义
    ├── tools/*.py               # CI 工具脚本
    ├── ci/*.py                  # 烧录计划 / 结果 schema
    └── requirements.txt         # Python 依赖
    │
    ▼
GR5526 Hardware Agent (label: gr5526-hw)
    │
    ├── 本地 Bootloader 项目      (BL_PROJECT_PATH)
    ├── 本地 APP 项目             (APP_PROJECT_PATH)
    ├── GR5xxx_console.exe       (烧录工具)
    ├── J-Link                   (调试接口)
    └── DUT                      (被测设备)
```

> **注意**：固件源码**不**存储在 CI SCM 仓库中。固件项目通过构建参数 `BL_PROJECT_PATH` / `APP_PROJECT_PATH` 在构建时指定本地路径。

## 流水线阶段

| 阶段 | 子阶段 | 说明 |
|---|---|---|
| **1. Prepare Environment** | 1.1 Python Venv Setup | 创建/复用虚拟环境，安装 requirements.txt |
| | 1.2 Environment Check | J-Link 自动检测、工具链检查、项目/SDK/CI 工具存在性检查、Python 语法检查 |
| **2. Build** (并行) | 2.1 Build Bootloader | mingw32-make 编译 → GR5xxx_console generate → bl_fw.bin |
| | 2.2 Build APP | mingw32-make 编译（含链接失败 response file 重试）→ generate_image_info.py → app_fw.bin |
| **3. Generate Firmware Metadata** | — | firmware_metadata.py generate → firmware_metadata.json |
| **4. Flash** | 4.1 Detect Firmware Layout | 从 .map / .bin 检测 BL/APP 地址、RTT 地址、Bank B 范围 |
| | 4.2 Verify Firmware Metadata | 验证 git_commit 与当前 HEAD 一致 |
| | 4.3 Generate & Validate Flash Plan | flash_plan.py generate + validate |
| | 4.4 Locate Firmware Images | 定位 bl_fw.bin / app_fw.bin |
| | 4.5 Hardware Flash Confirmation | **人工确认**（input 步骤，仅 DRY_RUN=false 时触发） |
| | 4.6 Erase Flash Regions | 擦除 BL + Bank A + Bank B，NVDS 保留 |
| | 4.7 Program APP (FIRST) | GR5xxx_console program --erase 2 |
| | 4.8 Program Bootloader (LAST) | GR5xxx_console program --erase 2（SCA 最终指向 BL） |
| | 4.9 Flash Verify | **MANDATORY GATE**：dump Bank A + SCA，verify_flash.py 校验 |
| | 4.10 Reset Device | GR5xxx_console reset（禁 J-Link reset） |
| **5. RTT Diagnostic** | — | test_rtt_with_jump.py，失败标记 UNSTABLE（不 FAIL） |

## 硬规则（MANDATORY - 不可修改）

1. **所有烧录操作使用 GR5xxx_console**（erase/program/dump/reset）
2. **禁止 J-Link flash/reset**
3. **烧录顺序：App FIRST，Bootloader LAST**
4. **只擦除 BL 区域、Bank A、Bank B；NVDS 保留；禁止 eraseall**
5. **生产地址来自 detect_firmware_layout.py**，不硬编码
6. **DRY_RUN 默认 true**，真实烧录需人工确认

## 构建参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `DRY_RUN` | boolean | `true` | 只验证/编译/规划，不修改硬件 flash |
| `SKIP_BUILD` | boolean | `false` | 跳过固件编译，使用已有固件 |
| `SKIP_FLASH` | boolean | `false` | 跳过所有烧录操作 |
| `ALLOW_PREBUILT_FIRMWARE` | boolean | `false` | 编译失败时允许使用已有固件 |
| `ALLOW_LAYOUT_FALLBACK` | boolean | `false` | 布局检测失败时使用默认地址（仅开发） |
| `BL_PROJECT_PATH` | string | `D:\...\bootloader\GCC` | Bootloader 项目目录（含 Makefile） |
| `APP_PROJECT_PATH` | string | `D:\...\app\GCC` | APP 项目目录（含 Makefile） |
| `BL_KEYWORD` | string | `''` | BL RTT 成功关键字（空=任意输出） |
| `APP_KEYWORD` | string | `''` | APP RTT 成功关键字（空=任意输出） |

## 环境变量（需根据硬件 Agent 配置）

| 变量 | 说明 | 示例 |
|---|---|---|
| `BL_SDK` | Bootloader SDK 路径 | `D:\...\GR5526_SDK_V1.0.4` |
| `APP_SDK` | APP SDK 路径 | `D:\...\GR5526_SDK_V1.0.4` |
| `GR_CONSOLE` | GR5xxx_console.exe 路径 | `D:\Program Files (x86)\Goodix\GProgrammer\GR5xxx_console.exe` |

> 这些变量在 `Jenkinsfile` 的 `environment` 块中配置，换机器时需修改。建议后续通过 Jenkins 全局环境变量或 Node 标签环境变量管理。

## 目录结构

```
repo root/
├── Jenkinsfile              # 流水线定义（声明式 Pipeline）
├── requirements.txt         # Python 依赖（pylink-square, pyserial, paho-mqtt）
├── .gitignore
├── README.md
├── Balboa.jlink             # J-Link 脚本
├── ci/
│   ├── flash_plan.py        # 烧录计划生成与验证
│   └── result_schema.json   # 测试结果 JSON Schema
├── tools/
│   ├── jlink_detect.py             # J-Link 自动检测（输出 key=value）
│   ├── detect_firmware_layout.py   # 固件布局检测（地址/RTT/分区）
│   ├── generate_image_info.py      # APP 镜像 Image Info 生成
│   ├── firmware_metadata.py        # 固件元数据生成与验证
│   ├── verify_flash.py             # 烧录验证（MANDATORY GATE）
│   └── test_rtt_with_jump.py       # RTT 诊断测试（BL jump to APP）
└── artifacts/               # 构建产物（不提交到 git）
    ├── firmware_metadata.json
    ├── flash_plan.json
    └── test_result.json
```

## 快速开始

### 1. 配置 Jenkins 作业

- 新建 **Pipeline** 项目，命名 `gr5526-ci`
- Pipeline → Definition → **Pipeline script from SCM**
- SCM → Git，填入仓库 URL
- Script Path → `Jenkinsfile`
- 限制项目运行节点 → `gr5526-hw`

### 2. 准备硬件 Agent

- 安装 J-Link 软件、GR5xxx_console、arm-none-eabi-gcc、mingw32-make
- 连接 J-Link 和 DUT
- 配置 Node 标签为 `gr5526-hw`

### 3. 首次运行（DRY_RUN）

```
Build with Parameters → DRY_RUN=true → Build
```

验证环境检测、编译、布局检测、烧录计划生成全部通过。

### 4. 真实烧录

```
Build with Parameters → DRY_RUN=false → Build
→ Stage 4.5 点击 "Flash Device" 确认
```

## 工具脚本说明

### tools/jlink_detect.py
自动检测已连接的 J-Link，输出 `JLINK_PATH`、`JLINK_SERIAL`、`JLINK_IDX`、`JLINK_USB_IDX`。

### tools/detect_firmware_layout.py
从 bootloader .map、app .map、bl_fw.bin、app_fw.bin 中解析：
- `BL_ADDR` / `BL_END` / `APP_ADDR` / `APP_END`
- `BANK_B_ADDR` / `BANK_B_END`
- `BL_RTT_ADDR` / `APP_RTT_ADDR`

### tools/generate_image_info.py
为 APP 镜像添加 Image Info 头（GR5xxx 启动要求）。

### tools/firmware_metadata.py
- `generate`：生成 firmware_metadata.json（芯片、SDK 版本、构建号、git commit）
- `verify`：验证 metadata 中 git_commit 与当前工作区 HEAD 一致

### ci/flash_plan.py
- `generate`：根据地址范围生成烧录计划 JSON
- `validate`：验证计划符合硬规则（NVDS 保留、App-first/BL-last、无 eraseall）

### tools/verify_flash.py
烧录后验证（MANDATORY GATE）：
- Bank A 非全 0xFF（APP 已烧录）
- SCA Boot_Info 非全 0xFF（--erase 2 已写入）
- SCA 中包含 BL 地址字节

### tools/test_rtt_with_jump.py
通过 J-Link RTT 读取 BL 和 APP 的启动日志，支持 jump 到 APP 后继续读取。失败不导致构建 FAIL，标记 UNSTABLE。

## 安全机制

| 机制 | 位置 | 作用 |
|---|---|---|
| `DRY_RUN` 默认 true | 参数 | 默认不碰硬件 |
| `disableConcurrentBuilds()` | options | 防止两个构建同时操作同一硬件 |
| `timeout(30 MINUTES)` | options | 防止构建卡死占用硬件 |
| Stage 4.5 人工确认 | input | 真实烧录前必须人工点击 |
| Stage 4.9 MANDATORY GATE | verify_flash.py | 烧录验证失败立即停止，不进入 RTT |
| `ALLOW_PREBUILT_FIRMWARE` 默认 false | 参数 | 防止误用旧固件 |
| `ALLOW_LAYOUT_FALLBACK` 默认 false | 参数 | 防止使用默认地址烧录生产设备 |

## 故障排查

### J-Link 检测失败
- 检查 USB 连接
- 确认 J-Link 驱动已安装
- 运行 `tools/jlink_detect.py` 手动查看输出

### 编译失败
- 检查 `BL_PROJECT_PATH` / `APP_PROJECT_PATH` 是否正确
- 检查 `arm-none-eabi-gcc` / `mingw32-make` 是否在 PATH
- APP 链接过长时会自动重试 response file

### 烧录验证失败
- 查看 `verify_bank_a.bin` / `verify_sca.bin` 的 hex dump
- 确认 GR5xxx_console 版本支持 `--erase 2`
- 确认烧录顺序（App FIRST, BL LAST）

### RTT 测试失败
- RTT 是诊断项，失败只标记 UNSTABLE
- 检查 `BL_RTT_ADDR` / `APP_RTT_ADDR` 是否正确
- 可通过 `BL_KEYWORD` / `APP_KEYWORD` 指定成功关键字
