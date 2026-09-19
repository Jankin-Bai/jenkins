// ============================================================================
// gr5526-ci : GR5526 compile -> flash -> test closed loop  (REFACTORED)
// ============================================================================
//
// 本文件只做编排（WHAT / WHEN / WHERE）。所有 HOW 在 ci/run.py 和 tools/*.py。
// 设计规则见 jenkins-mcp-master skill: references/jenkinsfile-design-rules.md
//
// 数据流（全部走 artifact，不走 env / stdout 解析）：
//   artifacts/hardware_context.json   <- jlink_detect.py (preflight)
//   artifacts/flash_plan.json         <- detect_layout.py + flash_plan.py
//   artifacts/firmware_metadata.json  <- firmware_metadata.py
//   artifacts/bl_build.json / app_build.json  <- build-bl / build-app
//   artifacts/test_result.json        <- collect-result
//
// 硬规则（不变）：
//   - 所有 flash 操作走 GR5xxx_console（gr_console.py 封装）
//   - 不用 J-Link flash/reset
//   - App FIRST, Bootloader LAST
//   - 只擦 BL / Bank A / Bank B，NVDS preserved，不 eraseall
//   - DRY_RUN 默认 true
// ============================================================================

pipeline {

    agent { label 'gr5526-hw' }

    options {
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timeout(time: 30, unit: 'MINUTES')
        // 单 label + disableConcurrentBuilds 已实现 DUT 互斥（规则14）
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        timestamps()
    }

    // --------------------------------------------------------------------
    // 参数：保留现有 boolean（RUN_MODE 收敛留作下一步技术债，见 NOTES）
    // --------------------------------------------------------------------
    parameters {
        booleanParam(name: 'DRY_RUN',                    defaultValue: true,  description: '只校验/构建/规划，不写 flash')
        booleanParam(name: 'SKIP_BUILD',                defaultValue: false, description: '跳过固件构建，用已有产物')
        booleanParam(name: 'SKIP_FLASH',                defaultValue: false, description: '跳过所有硬件烧写')
        booleanParam(name: 'WAIT_FOR_HUMAN_CONFIRMATION', defaultValue: false, description: 'DRY_RUN=false 时是否等待人工确认再烧写')
        booleanParam(name: 'ALLOW_PREBUILT_FIRMWARE',   defaultValue: false, description: '构建失败时允许使用已有固件')
        booleanParam(name: 'ALLOW_LAYOUT_FALLBACK',      defaultValue: false, description: '布局检测失败时允许 fallback（仅开发）')

        string(name: 'BL_PROJECT_PATH', defaultValue: 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli\\w4\\wc2\\bootloader\\GCC', description: 'Bootloader 构建目录（含 Makefile）')
        string(name: 'APP_PROJECT_PATH', defaultValue: 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli\\w4\\wc2\\app\\GCC',          description: 'APP 构建目录（含 Makefile）')
        string(name: 'BL_KEYWORD',  defaultValue: '', description: 'BL RTT 成功关键字，空=任意输出')
        string(name: 'APP_KEYWORD', defaultValue: '', description: 'APP RTT 成功关键字，空=任意输出')
    }

    // --------------------------------------------------------------------
    // 环境变量：只描述执行环境（规则19）。业务状态全部走 artifact。
    // BL_GCC/APP_GCC 映射到参数，供 run.py 和 build_app.bat 使用。
    // TODO(m3): BL_SDK / APP_SDK / GR_CONSOLE 挪到 Node 环境变量
    // --------------------------------------------------------------------
    environment {
        CI_ROOT   = "${WORKSPACE}"
        VENV_PY   = "${WORKSPACE}\\.venv\\Scripts\\python.exe"
        TOOLS     = "${WORKSPACE}\\tools"
        CI_DIR    = "${WORKSPACE}\\ci"
        ARTIFACTS = "${WORKSPACE}\\artifacts"
        CHIP      = 'GR5526'

        BL_GCC   = "${params.BL_PROJECT_PATH}"
        APP_GCC  = "${params.APP_PROJECT_PATH}"
        BL_SDK   = 'D:/Users/Administrator/Documents/code/wingcard_cli/GR5526_SDK_V1.0.4'
        APP_SDK  = 'D:/Users/Administrator/Documents/code/wingcard_cli/GR5526_SDK_V1.0.4'
        GR_CONSOLE = 'D:\\Program Files (x86)\\Goodix\\GProgrammer\\GR5xxx_console.exe'
    }

    stages {

        // ================================================================
        // Stage 0: Checkout
        // ================================================================
        stage('0. Checkout SCM') {
            steps {
                retry(3) {
                    checkout scm
                }
            }
        }

        // ================================================================
        // Stage 1: Prepare Environment
        // ================================================================
        stage('1. Prepare Environment') {
            stages {
                stage('1.1 Setup venv') {
                    steps {
                        bat '@echo off && call "%CI_ROOT%\\scripts\\setup_venv.bat"'
                    }
                }
                stage('1.2 Preflight & Detect Hardware') {
                    steps {
                        // preflight: 工具/SDK/Makefile 存在性 + py_compile + jlink_detect
                        // 产物: artifacts/hardware_context.json
                        bat '@"%VENV_PY%" "%CI_DIR%\\run.py" preflight'
                    }
                }
            }
        }

        // ================================================================
        // Stage 2: Build (BL / APP 并行，互不依赖)
        // ================================================================
        stage('2. Build') {
            when { expression { return !params.SKIP_BUILD.toBoolean() } }
            parallel {
                stage('2.1 Build Bootloader') {
                    steps {
                        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" build-bl'
                        }
                    }
                }
                stage('2.2 Build APP') {
                    steps {
                        catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" build-app'
                        }
                    }
                }
            }
        }

        // ================================================================
        // Stage 3: Firmware metadata
        // ================================================================
        stage('3. Firmware Metadata') {
            when { expression { return !params.SKIP_BUILD.toBoolean() } }
            steps {
                bat '@"%VENV_PY%" "%CI_DIR%\\run.py" metadata'
            }
        }

        // ================================================================
        // Stage 4: Flash  (8 步链：Detect->Plan->Validate->Gate->Erase->Prog->Verify->Reset)
        // ================================================================
        stage('4. Flash') {
            when { expression { return !params.SKIP_FLASH.toBoolean() } }
            stages {

                stage('4.1 Detect Layout') {
                    steps {
                        // 产物: artifacts/flash_plan.json（含地址表、clamp、fallback 决策）
                        bat '@"%VENV_PY%" "%CI_DIR%\\run.py" detect-layout'
                    }
                }

                stage('4.2 Verify Metadata') {
                    steps {
                        bat '@"%VENV_PY%" "%CI_DIR%\\run.py" verify-metadata'
                    }
                }

                stage('4.3 Validate Flash Plan') {
                    steps {
                        bat '@"%VENV_PY%" "%CI_DIR%\\run.py" validate-plan'
                    }
                }

                stage('4.4 Locate Images') {
                    steps {
                        // 找 bl_fw.bin / app_fw.bin，写回 flash_plan.json
                        bat '@"%VENV_PY%" "%CI_DIR%\\run.py" locate-images'
                    }
                }

                stage('4.5 Safety Gate') {
                    when { expression { return !params.DRY_RUN.toBoolean() } }
                    steps {
                        script {
                            if (params.WAIT_FOR_HUMAN_CONFIRMATION.toBoolean()) {
                                input message: """
============================================================
GR5526 HARDWARE FLASH CONFIRMATION
============================================================
即将对 DUT 执行 Erase + Program APP + Program BL + Verify。
NVDS 保留，不做 eraseall。
确认硬件已接好、J-Link 已连接后继续。
============================================================
""", ok: 'Flash Device'
                            } else {
                                echo '[Safety Gate] WAIT_FOR_HUMAN_CONFIRMATION=false，无人值守继续。'
                            }
                        }
                    }
                }

                stage('4.6 Erase') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" erase'
                        }
                    }
                }

                stage('4.7 Program APP (FIRST)') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" program-app'
                        }
                    }
                }

                stage('4.8 Program Bootloader (LAST)') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" program-bl'
                        }
                    }
                }

                stage('4.9 Verify Flash') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" verify-flash'
                        }
                    }
                }

                stage('4.10 Reset') {
                    steps {
                        timeout(time: 1, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" reset'
                        }
                        sleep(time: 5, unit: 'SECONDS')
                    }
                }
            }
        }

        // ================================================================
        // Stage 5: RTT Diagnostic (失败 = UNSTABLE，不 FAIL)
        // ================================================================
        stage('5. RTT Diagnostic') {
            when { expression { return !params.DRY_RUN.toBoolean() && !params.SKIP_FLASH.toBoolean() } }
            steps {
                catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE') {
                    timeout(time: 30, unit: 'MINUTES') {
                        bat '@"%VENV_PY%" "%CI_DIR%\\run.py" rtt'
                    }
                }
            }
        }
    }

    // --------------------------------------------------------------------
    // post: 只做轻量归档与通知（规则17）。结果收集在 collect-result 里。
    // --------------------------------------------------------------------
    post {
        always {
            script {
                // 收集结果到 test_result.json（Python 读各 artifact 聚合）
                bat '@"%VENV_PY%" "%CI_DIR%\\run.py" collect-result'

                // 核心产物：缺失即失败（规则18，allowEmptyArchive=false）
                archiveArtifacts(
                    artifacts: 'artifacts/firmware_metadata.json,artifacts/flash_plan.json,artifacts/hardware_context.json,artifacts/test_result.json',
                    allowEmptyArchive: false,
                    fingerprint: true
                )
                // 临时/调试产物：允许空
                archiveArtifacts(
                    artifacts: 'artifacts/**/*.json,artifacts/*.bin,rtt_result.json,verify_*.bin',
                    allowEmptyArchive: true
                )
            }
        }
        success  { echo 'gr5526-ci PASSED.' }
        failure  { echo 'gr5526-ci FAILED.' }
        unstable { echo 'gr5526-ci UNSTABLE (RTT diagnostic may have failed).' }
        aborted  { echo 'gr5526-ci ABORTED.' }
    }
}
