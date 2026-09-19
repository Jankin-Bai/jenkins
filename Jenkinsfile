// ============================================================================
// gr5526-ci-v2 : GR5526 compile -> flash -> test closed loop  (v2 refactor)
// ============================================================================
//
// 本文件只做编排（WHAT / WHEN / WHERE）。所有 HOW 在 ci/run.py。
// 设计规则见 jenkins-mcp-master skill: references/jenkinsfile-design-rules.md
//
// 数据流（全部走 artifact，不走 env / stdout 解析）：
//   artifacts/hardware_context.json   <- preflight
//   artifacts/flash_plan.json         <- plan
//   artifacts/bl_build.json / app_build.json  <- build-bl / build-app
//   artifacts/test_result.json        <- collect-result
//
// 硬规则（不变）：
//   - 所有 flash 操作走 GR5xxx_console（gr_console.py 封装）
//   - App FIRST, Bootloader LAST
//   - 只擦 BL / Bank A / Bank B，NVDS preserved
//   - DRY_RUN 默认 true
// ============================================================================

pipeline {

    agent { label 'gr5526-hw' }

    options {
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        skipDefaultCheckout(true)
        timestamps()
    }

    // --------------------------------------------------------------------
    // 参数：编译配置让构建时选（规则11：choice 而非 boolean 爆炸）
    // --------------------------------------------------------------------
    parameters {
        booleanParam(name: 'DRY_RUN',                    defaultValue: true,  description: '只校验/构建/规划，不写 flash')
        booleanParam(name: 'SKIP_BUILD',                defaultValue: false, description: '跳过固件构建，用已有产物')
        booleanParam(name: 'SKIP_FLASH',                defaultValue: false, description: '跳过所有硬件烧写')
        booleanParam(name: 'SKIP_ERASE',                defaultValue: false, description: '跳过擦除')
        booleanParam(name: 'WAIT_FOR_HUMAN_CONFIRMATION', defaultValue: false, description: 'DRY_RUN=false 时是否等待人工确认再烧写')

        choice(name: 'BUILD_MODE',  choices: ['release', 'debug'], description: 'release=FW_release=1; debug=FW_release=0+DEBUG_IDLE=1')
        choice(name: 'BOARD_TYPE',  choices: ['TK_PAD', 'TK_1_1', 'TK'], description: '板子类型')
        booleanParam(name: 'CLI_PORT',  defaultValue: true, description: '启用 CLI 串口')

        string(name: 'PROJECT_ROOT', defaultValue: 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli', description: '工程根目录（含 bootloader/ 和 ble_app_uart_c/）')
        string(name: 'BL_KEYWORD',  defaultValue: '', description: 'BL RTT 成功关键字，空=任意输出')
        string(name: 'APP_KEYWORD', defaultValue: '', description: 'APP RTT 成功关键字，空=任意输出')
    }

    // --------------------------------------------------------------------
    // 环境变量：只描述执行环境（规则19）。业务状态全部走 artifact。
    // --------------------------------------------------------------------
    environment {
        CI_ROOT   = "${WORKSPACE}"
        VENV_PY   = "${WORKSPACE}\\.venv\\Scripts\\python.exe"
        TOOLS     = "${WORKSPACE}\\tools"
        CI_DIR    = "${WORKSPACE}\\ci"
        ARTIFACTS = "${WORKSPACE}\\artifacts"
        CHIP      = 'GR5526'
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
                stage('1.2 Preflight') {
                    steps {
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
        // Stage 3: Plan & Validate
        // ================================================================
        stage('3. Plan & Validate') {
            steps {
                bat '@"%VENV_PY%" "%CI_DIR%\\run.py" plan'
                bat '@"%VENV_PY%" "%CI_DIR%\\run.py" validate'
            }
        }

        // ================================================================
        // Stage 4: Flash  (Safety Gate -> Erase -> Program APP -> Program BL -> Verify)
        // ================================================================
        stage('4. Flash') {
            when { expression { return !params.SKIP_FLASH.toBoolean() } }
            stages {

                stage('4.1 Safety Gate') {
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
                                echo '[Safety Gate] WAIT_FOR_HUMAN_CONFIRMATION=false, unattended.'
                            }
                        }
                    }
                }

                stage('4.2 Erase') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" erase'
                        }
                    }
                }

                stage('4.3 Program APP (FIRST)') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" program-app'
                        }
                    }
                }

                stage('4.4 Program Bootloader (LAST)') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" program-bl'
                        }
                    }
                }

                stage('4.5 Verify') {
                    steps {
                        timeout(time: 5, unit: 'MINUTES') {
                            bat '@"%VENV_PY%" "%CI_DIR%\\run.py" verify'
                        }
                    }
                }
            }
        }
    }

    // --------------------------------------------------------------------
    // post: 只做轻量归档与通知（规则17）。
    // --------------------------------------------------------------------
    post {
        always {
            script {
                bat '@"%VENV_PY%" "%CI_DIR%\\run.py" collect-result'

                archiveArtifacts(
                    artifacts: 'artifacts/**/*.json',
                    allowEmptyArchive: false,
                    fingerprint: true
                )
            }
        }
        success  { echo 'gr5526-ci-v2 PASSED.' }
        failure  { echo 'gr5526-ci-v2 FAILED.' }
        unstable { echo 'gr5526-ci-v2 UNSTABLE.' }
        aborted  { echo 'gr5526-ci-v2 ABORTED.' }
    }
}
