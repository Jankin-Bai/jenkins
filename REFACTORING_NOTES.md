# gr5526-ci 整改说明（REFACTORING NOTES）

本目录是按 21 条设计规则整改后的**目标骨架**。Jenkinsfile 已完整，`ci/run.py` 是总入口骨架（标注 TODO 的地方需要你或 Python skill 填实现），两个 `.bat` 已从旧 Jenkinsfile 抽出。

## 目录结构

```
gr5526-ci-refactor/
├── Jenkinsfile                  # 薄编排层，~180 行，无业务逻辑
├── ci/
│   ├── run.py                   # 总入口，15 个子命令
│   └── flash/
│       └── gr_console.py        # GR5xxx_console 单一封装（规则9）
└── scripts/
    ├── setup_venv.bat           # 从 Stage 1.1 抽出
    └── build_app.bat            # 从 Stage 2.2 抽出（含 response file fallback）
```

## 现有 tools/*.py 需要小改的点（不重写，只改输出接口）

按规则 4/6/19，这些脚本**不要再用 stdout 打 key=value**，改为直接写 JSON 到 `artifacts/`：

| 现有脚本 | 现在的输出 | 改造后 |
|---|---|---|
| `tools/jlink_detect.py` | stdout `JLINK_PATH=...` 等 | 直接写 `artifacts/hardware_context.json` 的 `jlink` 段 |
| `tools/detect_firmware_layout.py` | stdout `BL_ADDR=...` 等 | 直接写 `artifacts/flash_plan.json`；**BANK_B_END clamp 逻辑从 Jenkinsfile 搬进来**；fallback 决策也在脚本里（读 `ALLOW_LAYOUT_FALLBACK` env） |
| `tools/flash_plan.py` | generate/validate 子命令 | 保留；validate 读 `flash_plan.json` |
| `tools/firmware_metadata.py` | generate/verify 子命令 | 保留；generate 增加 `--bl-status` / `--app-status` 参数（从 bl_build.json / app_build.json 读） |
| `tools/generate_image_info.py` | 命令行参数 | 保留，由 `ci/run.py build-app` 调用 |
| `tools/verify_flash.py` | 读 env | 改为读 `artifacts/flash_plan.json` |
| `tools/test_rtt_with_jump.py` | 命令行参数 | 保留，由 `ci/run.py rtt` 调用 |

> 这一步需要你把现有脚本源码贴出来，或授权我调 Python skill 来改——我没看过它们的实现，不臆测内部逻辑。

## 对照 21 条规则的整改情况

| 规则 | 整改前 | 整改后 |
|---|---|---|
| 1 编排层 | Jenkinsfile 含大量 Groovy 业务逻辑 | Jenkinsfile 只调 `ci/run.py <cmd>` |
| 2 WHAT/HOW | HOW 在 Jenkinsfile | HOW 全在 ci/run.py + tools/*.py |
| 3 bat 只做 glue | Stage 1.1/2.2/4.4 内联大段 bat | 抽到 scripts/*.bat |
| 4 不解析 stdout | `bat(returnStdout)` + Groovy split | 脚本直接写 JSON，Jenkinsfile 不解析 |
| 5 不用 env 当数据库 | env.JLINK_*/env.BL_ADDR 等跨 stage 传递 | 全部走 artifact JSON |
| 6 artifact 传状态 | 部分用 | hardware_context/flash_plan/firmware_metadata/test_result 全套 |
| 7 ci/hardware 等分层 | 暂未 | TODO(m1)：后续把 tools/ 按 ci/hardware、ci/firmware、ci/flash 重排 |
| 8 8 步链 | 已基本对齐 | 4.1~4.10 严格对应 Detect→Plan→Validate→Gate→Erase→Prog→Verify→Reset |
| 9 单一硬件入口 | grConsole 在 Jenkinsfile | `ci/flash/gr_console.py`，所有 erase/program/dump/reset/generate 走它 |
| 10 不算地址 | Jenkinsfile 硬编码 + clamp | 地址表在 flash_plan.json，clamp 在 detect_layout.py |
| 11 boolean 爆炸 | 6 个 boolean | **暂保留**（RUN_MODE 收敛留作下一步，避免改变使用习惯） |
| 12 业务 stage 名 | OK | 保持 |
| 13 parallel 独立 | BL/APP 并行 OK | 保持 |
| 14 DUT 互斥 | disableConcurrentBuilds + label | 保持，注释明确 |
| 15 单操作 timeout | 只有顶层 30min | 4.6~4.10 各自 1~5min timeout |
| 16 ping 当 sleep | 2 处 | setup_venv.bat 用 `timeout /t 10`；4.10 用 Jenkins `sleep` |
| 17 post 轻量 | ~60 行 Groovy 组 JSON | post 只调 `collect-result` + 两条 archiveArtifacts |
| 18 allowEmptyArchive | true（全部产物） | 核心 4 个 JSON `false`，其余 `true` |
| 19 env/artifact 分离 | env 混着用 | env 只放路径/开关，动态状态全 artifact |
| 20 ci/run.py 总入口 | 无 | 新增 ci/run.py，15 个子命令 |
| 21 缺脚本处理 | — | 本文件即按此规则产出 |

## 你需要决策/补充的点

1. **Safety Gate 默认行为**：现在维持现状（WAIT_FOR_HUMAN_CONFIRMATION=false 时无人值守直接烧）。是否要改成 `DRY_RUN=false` 时强制 input？
2. **RUN_MODE 参数化**：是否本轮做？建议下一轮，避免破坏现有构建参数习惯。
3. **现有 tools/*.py 源码**：需要你贴出来或授权我调 Python skill 改造输出接口。
4. **目录分层（规则7）**：是否本轮把 tools/ 重排到 ci/hardware、ci/firmware、ci/flash？涉及路径改动，建议单独一次 PR。
5. **BL_SDK / APP_SDK / GR_CONSOLE**：注释里 TODO 挪到 Node 环境变量，本轮先保留在 environment{}。

## 落地步骤建议

1. 把本目录的 Jenkinsfile 内容覆盖到 SCM 仓库根
2. 把 ci/、scripts/ 复制到仓库对应位置
3. 改造 tools/*.py 输出接口（见上表）
4. 在本地/Agent 上先跑 `python ci/run.py preflight`、`... detect-layout` 验证脚本链路
5. Jenkins 上触发一次 DRY_RUN=true 构建，确认 stage 全部走通
6. 再 DRY_RUN=false 小范围验证
