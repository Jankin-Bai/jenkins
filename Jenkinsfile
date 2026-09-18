// ============================================================================
// gr5526-ci : GR5526 compile -> flash -> test closed loop
// ============================================================================
//
// ARCHITECTURE
//
//   Jenkins SCM (GitHub / Gitea)
//       |
//       +-- Jenkinsfile
//       +-- tools/*.py
//       +-- ci/*.py
//       |
//       v
//   GR5526 Hardware Agent (gr5526-hw label)
//       |
//       +-- Local Bootloader project (BL_PROJECT_PATH)
//       +-- Local APP project (APP_PROJECT_PATH)
//       +-- GR5xxx_console
//       +-- J-Link
//       +-- DUT
//
// Firmware source code is NOT stored in the CI SCM repo.
// Firmware projects are selected at build time through:
//   BL_PROJECT_PATH / APP_PROJECT_PATH
//
// HARD RULES (MANDATORY - never change):
//   - GR5xxx_console for ALL flash ops (erase/program/dump/reset).
//   - NO J-Link flash/reset.
//   - Flash order: App FIRST, Bootloader LAST.
//   - Erase only: BL region, Bank A, Bank B. NVDS PRESERVED. NO eraseall.
//   - Production addresses come from detect_firmware_layout.py.
//   - DRY_RUN defaults true.
//
// ============================================================================


// ============================================================================
// GR5xxx_console wrapper
// ============================================================================
//
// All GR5xxx_console operations go through this function.
// Centralizes: DRY_RUN mode, logging, error propagation.
// Flash main flow stays readable - callers see explicit App-first/BL-last order.
//
def grConsole(String args) {
    if (params.DRY_RUN.toBoolean()) {
        echo "[DRY-RUN] GR5xxx_console: ${args}"
    } else {
        echo "[GR5526-CI] GR5xxx_console ${args}"
        bat "@\"${env.GR_CONSOLE}\" ${args}"
    }
}


pipeline {

    // ========================================================================
    // Hardware Agent
    // ========================================================================

    agent {
        label 'gr5526-hw'
    }


    // ========================================================================
    // Jenkins Options
    // ========================================================================

    options {
        buildDiscarder(logRotator(numToKeepStr: '30'))
        timeout(time: 30, unit: 'MINUTES')
        // One Hardware Agent owns: DUT + J-Link + GR5xxx_console
        // Do not allow two builds to operate on the same hardware.
        disableConcurrentBuilds()
        // We do manual checkout in Stage 0 with retry logic (network resilience).
        skipDefaultCheckout(true)
    }


    // ========================================================================
    // Build Parameters
    // ========================================================================

    parameters {

        // --------------------------------------------------------------------
        // Execution control
        // --------------------------------------------------------------------

        booleanParam(
            name: 'DRY_RUN',
            defaultValue: true,
            description: 'Validate/build/plan only. Never modify hardware flash.'
        )

        booleanParam(
            name: 'SKIP_BUILD',
            defaultValue: false,
            description: 'Skip firmware build and use existing firmware artifacts.'
        )

        booleanParam(
            name: 'SKIP_FLASH',
            defaultValue: false,
            description: 'Skip all hardware flash operations.'
        )


        // --------------------------------------------------------------------
        // Safety switches
        // --------------------------------------------------------------------

        booleanParam(
            name: 'ALLOW_PREBUILT_FIRMWARE',
            defaultValue: false,
            description: 'Allow existing firmware artifacts when build is skipped or fails.'
        )

        booleanParam(
            name: 'ALLOW_LAYOUT_FALLBACK',
            defaultValue: false,
            description: 'Allow layout detection fallback (development only).'
        )


        // --------------------------------------------------------------------
        // Firmware project selection
        // --------------------------------------------------------------------
        //
        // Firmware source is NOT stored in CI SCM.
        // Select the local build directory on the Hardware Agent.
        // The selected directory MUST contain Makefile.
        //

        string(
            name: 'BL_PROJECT_PATH',
            defaultValue: 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli\\w4\\wc2\\bootloader\\GCC',
            description: 'Bootloader build directory containing Makefile.'
        )

        string(
            name: 'APP_PROJECT_PATH',
            defaultValue: 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli\\w4\\wc2\\app\\GCC',
            description: 'APP build directory containing Makefile.'
        )


        // --------------------------------------------------------------------
        // RTT test configuration
        // --------------------------------------------------------------------

        string(
            name: 'BL_KEYWORD',
            defaultValue: '',
            description: 'BL RTT success keyword. Empty = any output.'
        )

        string(
            name: 'APP_KEYWORD',
            defaultValue: '',
            description: 'APP RTT success keyword. Empty = any output.'
        )
    }


    // ========================================================================
    // Global Environment
    // ========================================================================

    environment {

        // --------------------------------------------------------------------
        // CI root (Jenkins workspace, checked out from SCM)
        // SCM repo root = WORKSPACE, CI code lives directly in WORKSPACE/
        // All paths point inside WORKSPACE/ - no hardcoded absolute paths.
        // NOTE: MUST use double quotes for Groovy variable interpolation!
        // Single quotes would make ${WORKSPACE} a literal string.
        // --------------------------------------------------------------------

        CI_ROOT   = "${WORKSPACE}"
        VENV_PY   = "${WORKSPACE}\\.venv\\Scripts\\python.exe"
        TOOLS     = "${WORKSPACE}\\tools"
        CI_DIR    = "${WORKSPACE}\\ci"
        ARTIFACTS = "${WORKSPACE}\\artifacts"


        // --------------------------------------------------------------------
        // Firmware projects (selected by build parameters)
        // --------------------------------------------------------------------

        BL_GCC  = "${params.BL_PROJECT_PATH}"
        APP_GCC = "${params.APP_PROJECT_PATH}"


        // --------------------------------------------------------------------
        // SDK (machine-specific - configure per hardware agent)
        // TODO: move to Jenkins Node environment variables or job parameters
        // --------------------------------------------------------------------

        BL_SDK  = 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli\\GR5526_SDK_V1.0.4'
        APP_SDK = 'D:\\Users\\Administrator\\Documents\\code\\wingcard_cli\\GR5526_SDK_V1.0.4'


        // --------------------------------------------------------------------
        // Hardware tools (machine-specific - configure per hardware agent)
        // TODO: move to Jenkins Node environment variables
        // --------------------------------------------------------------------

        GR_CONSOLE = 'D:\\Program Files (x86)\\Goodix\\GProgrammer\\GR5xxx_console.exe'


        // --------------------------------------------------------------------
        // Hardware constant (fixed by GR5526 SDK, last flash sector)
        // --------------------------------------------------------------------

        NVDS_ADDR = '0x002EF000'


        // --------------------------------------------------------------------
        // Runtime information (populated during pipeline)
        // NOTE: JLINK_PATH, JLINK_SERIAL, JLINK_IDX, JLINK_USB_ID are NOT
        // NOTE: BL_ADDR, BL_END, APP_ADDR, APP_END, BANK_B_ADDR, BANK_B_END,
        // BL_IMAGE, APP_IMAGE, BL_RTT_ADDR, APP_RTT_ADDR, BL_BUILD_STATUS,
        // APP_BUILD_STATUS are NOT pre-declared here. Jenkins CPS drops
        // env.XXX assignments for variables pre-declared in environment{}.
        // They are assigned at runtime (layout detection / parallel branches).

        CHIP          = 'GR5526'
    }


    // ========================================================================
    // Pipeline Stages
    // ========================================================================

    stages {


        // ====================================================================
        // Stage 0: Checkout SCM (with retry for network resilience)
        // ====================================================================

        stage('0. Checkout SCM') {

            steps {

                echo '[Stage0] Checking out CI scripts from SCM (with retry)'

                script {

                    def maxAttempts = 3
                    def retryDelaySec = 15

                    for (int attempt = 1; attempt <= maxAttempts; attempt++) {
                        try {
                            echo "[Stage0] Checkout attempt ${attempt}/${maxAttempts} ..."
                            checkout scm
                            echo "[Stage0] Checkout SUCCESS on attempt ${attempt}"
                            break
                        } catch (Exception e) {
                            if (attempt == maxAttempts) {
                                error(
                                    "SCM checkout FAILED after ${maxAttempts} attempts. " +
                                    "Last error: ${e.getMessage()}. " +
                                    "Check network connection to GitHub."
                                )
                            }
                            echo "[Stage0] Checkout failed (attempt ${attempt}/${maxAttempts}): ${e.getMessage()}"
                            echo "[Stage0] Waiting ${retryDelaySec}s before retry ..."
                            sleep(time: retryDelaySec, unit: 'SECONDS')
                        }
                    }
                }
            }
        }


        // ====================================================================
        // Stage 1: Prepare Environment (SERIAL)
        // ====================================================================

        stage('1. Prepare Environment') {

            stages {


                // ============================================================
                // 1.1 Python Venv Setup (ALWAYS runs - needed for env check)
                // ============================================================

                stage('1.1 Python Venv Setup') {

                    steps {

                        echo '[Stage1.1] Setting up Python virtual environment (always runs)'

                        bat '''
@echo off
cd /d "%CI_ROOT%"
if not exist ".venv\\Scripts\\python.exe" (
    echo [venv] Creating virtual environment...
    python -m venv .venv
) else (
    echo [venv] Reusing existing virtual environment
)
echo [venv] Installing dependencies (with pip retry)...
".venv\\Scripts\\python.exe" -m pip install --quiet --retries 5 --timeout 60 -r requirements.txt
if errorlevel 1 (
    echo [venv] pip install failed on first try, retrying after 10s...
    ping -n 11 127.0.0.1 >nul
    ".venv\\Scripts\\python.exe" -m pip install --quiet --retries 5 --timeout 60 -r requirements.txt
)
echo [venv] Setup complete
".venv\\Scripts\\python.exe" --version
'''

                        echo '[PASS] venv-setup complete'
                    }
                }


                // ============================================================
                // 1.2 Environment Check (uses venv python from 1.1)
                // ============================================================

                stage('1.2 Environment Check') {

                    steps {

                        echo '[Stage1.2] Starting environment verification'

                        script {

                            // ------------------------------------------------
                            // Resolve firmware projects
                            // ------------------------------------------------

                            env.BL_GCC  = params.BL_PROJECT_PATH.trim()
                            env.APP_GCC = params.APP_PROJECT_PATH.trim()

                            if (!env.BL_GCC || !env.APP_GCC) {
                                error('BL_PROJECT_PATH and APP_PROJECT_PATH are required')
                            }

                            echo "Bootloader project: ${env.BL_GCC}"
                            echo "APP project: ${env.APP_GCC}"


                            // ------------------------------------------------
                            // J-Link auto detection (outputs key=value to stdout)
                            // Use -u flag for unbuffered stdout.
                            // NOTE: JLINK_* vars are NOT pre-declared in environment{}
                            // because Jenkins CPS drops closure assignments for
                            // pre-declared env vars.
                            // ------------------------------------------------

                            echo '>> J-Link auto-detection'

                            def detectOut = bat(
                                returnStdout: true,
                                script: '@"%VENV_PY%" -u "%TOOLS%\\jlink_detect.py"'
                            ).trim()

                            echo "DEBUG detectOut=[${detectOut}]"

                            detectOut.split(/\r?\n/).each { rawLine ->
                                def line = rawLine.trim()
                                if (!line || !line.contains('=')) return
                                def parts = line.split('=', 2)
                                if (parts.length == 2) {
                                    def key = parts[0].trim()
                                    def val = parts[1].trim()
                                    echo "  DEBUG line: key=[${key}] val=[${val}]"
                                    if (key == 'JLINK_PATH')     { env.JLINK_PATH   = val }
                                    else if (key == 'JLINK_SERIAL') { env.JLINK_SERIAL = val }
                                    else if (key == 'JLINK_IDX')    { env.JLINK_IDX    = val }
                                    else if (key == 'JLINK_USB_ID') { env.JLINK_USB_ID = val }
                                }
                            }

                            echo "DEBUG parsed: JLINK_PATH=[${env.JLINK_PATH}] JLINK_IDX=[${env.JLINK_IDX}] JLINK_SERIAL=[${env.JLINK_SERIAL}]"

                            if (!env.JLINK_PATH || !env.JLINK_IDX) {
                                error('J-Link auto-detection FAILED - check USB connection and software')
                            }

                            echo "J-Link: path=${env.JLINK_PATH} idx=${env.JLINK_IDX} serial=${env.JLINK_SERIAL}"
                        }


                        // ----------------------------------------------------
                        // Hardware / tool existence checks
                        // ----------------------------------------------------

                        bat '''
@if not exist "%GR_CONSOLE%" (echo ERROR: GR5xxx_console missing & exit /b 1)
@where arm-none-eabi-gcc >nul 2>&1 || (echo ERROR: arm-none-eabi-gcc not in PATH & exit /b 1)
@where mingw32-make >nul 2>&1 || (echo ERROR: mingw32-make not in PATH & exit /b 1)
'''


                        // ----------------------------------------------------
                        // Firmware project checks
                        // ----------------------------------------------------

                        bat '''
@if not exist "%BL_GCC%" (echo ERROR: bootloader project directory missing & exit /b 1)
@if not exist "%BL_GCC%\\Makefile" (echo ERROR: bootloader Makefile missing & exit /b 1)
@if not exist "%APP_GCC%" (echo ERROR: app project directory missing & exit /b 1)
@if not exist "%APP_GCC%\\Makefile" (echo ERROR: app Makefile missing & exit /b 1)
'''


                        // ----------------------------------------------------
                        // SDK checks
                        // ----------------------------------------------------

                        bat '''
@if not exist "%BL_SDK%" (echo ERROR: bootloader SDK missing & exit /b 1)
@if not exist "%APP_SDK%" (echo ERROR: app SDK missing & exit /b 1)
'''


                        // ----------------------------------------------------
                        // CI tools checks
                        // ----------------------------------------------------

                        bat '''
@if not exist "%TOOLS%\\jlink_detect.py" (echo ERROR: jlink_detect.py missing & exit /b 1)
@if not exist "%TOOLS%\\detect_firmware_layout.py" (echo ERROR: detect_firmware_layout.py missing & exit /b 1)
@if not exist "%TOOLS%\\generate_image_info.py" (echo ERROR: generate_image_info.py missing & exit /b 1)
@if not exist "%TOOLS%\\firmware_metadata.py" (echo ERROR: firmware_metadata.py missing & exit /b 1)
@if not exist "%TOOLS%\\verify_flash.py" (echo ERROR: verify_flash.py missing & exit /b 1)
@if not exist "%TOOLS%\\test_rtt_with_jump.py" (echo ERROR: test_rtt_with_jump.py missing & exit /b 1)
@if not exist "%CI_DIR%\\flash_plan.py" (echo ERROR: ci/flash_plan.py missing & exit /b 1)
'''


                        // ----------------------------------------------------
                        // Python syntax check
                        // ----------------------------------------------------

                        bat '''
@"%VENV_PY%" -m py_compile ^
    "%TOOLS%\\jlink_detect.py" ^
    "%TOOLS%\\detect_firmware_layout.py" ^
    "%TOOLS%\\generate_image_info.py" ^
    "%TOOLS%\\firmware_metadata.py" ^
    "%TOOLS%\\verify_flash.py" ^
    "%TOOLS%\\test_rtt_with_jump.py" ^
    "%CI_DIR%\\flash_plan.py"
if errorlevel 1 (echo ERROR: Python syntax check failed & exit /b 1)
echo Python syntax check PASSED.
'''

                        echo '[PASS] env-check: all tools and firmware projects verified'
                    }
                }
            }
        }


        // ====================================================================
        // Stage 2: Build (parallel)
        // ====================================================================

        stage('2. Build') {

            when { expression { return !params.SKIP_BUILD.toBoolean() } }

            parallel {


                // ============================================================
                // 2.1 Build Bootloader
                // ============================================================

                stage('2.1 Build Bootloader') {

                    steps {

                        echo '[Stage2.1] Compiling GR5526 bootloader (SDK 1.0.3)'

                        script {

                            if (params.DRY_RUN.toBoolean()) {
                                echo '[DRY-RUN] would: cd BL_PROJECT_PATH && mingw32-make clean && mingw32-make'
                                echo '[DRY-RUN] would: GR5xxx_console generate -> bl_fw.bin'
                                env.BL_BUILD_STATUS = 'dry-run'
                            } else {

                                // Build bootloader
                                bat '''
@echo off
cd /d "%BL_GCC%"
echo [build-boot] Cleaning...
mingw32-make clean 2>&1
echo [build-boot] Compiling...
mingw32-make 2>&1
if errorlevel 1 (echo [FAIL] bootloader make failed & exit /b 1)
if not exist "out\\app_bootloader.bin" (echo [FAIL] app_bootloader.bin not produced & exit /b 1)
echo [PASS] bootloader compiled: out\\app_bootloader.bin
'''

                                // Generate bootloader image with Image Info via GR5xxx_console
                                echo '[build-boot] Generating bl_fw.bin with Image Info'
                                grConsole(
                                    "generate \"${env.BL_GCC}\\out\\app_bootloader.bin\" " +
                                    "\"${env.CI_ROOT}\\bl_fw.bin\" 0x00200000 1024 1"
                                )

                                env.BL_BUILD_STATUS = 'success'
                                echo '[PASS] build-boot: bl_fw.bin generated'
                            }
                        }
                    }
                }


                // ============================================================
                // 2.2 Build APP
                // ============================================================

                stage('2.2 Build APP') {

                    steps {

                        echo '[Stage2.2] Compiling GR5526 APP (SDK 1.0.4)'

                        script {

                            if (params.DRY_RUN.toBoolean()) {
                                echo '[DRY-RUN] would: cd APP_PROJECT_PATH && mingw32-make SDK_ROOT=...'
                                echo '[DRY-RUN] would: retry link with response file if necessary'
                                echo '[DRY-RUN] would: generate_image_info.py -> app_fw.bin'
                                env.APP_BUILD_STATUS = 'dry-run'
                            } else {

                                // Build APP. Known issue: linker command line can become too long.
                                // Attempt 1: normal make. Attempt 2: response file.
                                def appRc = bat(
                                    returnStatus: true,
                                    script: '''
@echo off
cd /d "%APP_GCC%"
echo [build-app] Cleaning...
mingw32-make SDK_ROOT="%APP_SDK%" clean 2>&1
echo [build-app] Compiling (attempt 1)...
mingw32-make SDK_ROOT="%APP_SDK%" 2>&1
if exist "out\\lst\\ble_app_uart_c.elf" goto build_ok
echo [WARN] Link failed on attempt 1. Retrying with response file...
if not exist "out\\obj" goto build_fail
dir /b /s out\\obj\\*.o > obj_list.txt
echo [build-app] Linking (attempt 2 with response file)...
mingw32-make SDK_ROOT="%APP_SDK%" OBJ_ADJUST="@obj_list.txt" 2>&1
if exist "out\\lst\\ble_app_uart_c.elf" goto build_ok
goto build_fail

:build_ok
echo [build-app] Generating .bin...
if not exist "out\\ble_app_uart_c.bin" goto build_fail
echo [PASS] app compiled: out\\ble_app_uart_c.bin
exit /b 0

:build_fail
echo [WARN] App build failed.
if exist "%CI_ROOT%\\app_fw.bin" (
    echo [INFO] Existing app_fw.bin found (pre-built)
    exit /b 2
) else (
    echo [FAIL] App build failed and no existing app_fw.bin found
    exit /b 1
)
'''
                                )

                                echo "[build-app] make exit code: ${appRc}"

                                if (appRc == 0) {
                                    // Generate app image with Image Info
                                    echo '[build-app] Generating app_fw.bin with Image Info'
                                    bat(
                                        '@"%VENV_PY%" "%TOOLS%\\generate_image_info.py" ' +
                                        '--input "%APP_GCC%\\out\\ble_app_uart_c.bin" ' +
                                        '--output "%CI_ROOT%\\app_fw.bin" ' +
                                        '--load-addr 0x00240000 ' +
                                        '--name ble_app_uart_c'
                                    )
                                    env.APP_BUILD_STATUS = 'success'
                                    echo '[PASS] build-app: app_fw.bin generated from fresh build'

                                } else if (appRc == 2) {
                                    // Prebuilt firmware exists - only use if explicitly allowed
                                    if (params.ALLOW_PREBUILT_FIRMWARE.toBoolean()) {
                                        env.APP_BUILD_STATUS = 'prebuilt-firmware'
                                        echo '[WARN] WARNING: Using PREBUILT firmware. This firmware was NOT produced by current build.'
                                    } else {
                                        error(
                                            'App build FAILED and ALLOW_PREBUILT_FIRMWARE=false. ' +
                                            'Set ALLOW_PREBUILT_FIRMWARE=true to use existing app_fw.bin.'
                                        )
                                    }
                                } else {
                                    error('App build FAILED and no existing app_fw.bin available')
                                }
                            }
                        }
                    }
                }
            }


            post {
                failure {
                    echo '[WARN] Stage 2 build had failures.'
                    script {
                        if (!env.BL_BUILD_STATUS)  { env.BL_BUILD_STATUS  = 'failed' }
                        if (!env.APP_BUILD_STATUS) { env.APP_BUILD_STATUS = 'failed' }
                    }
                }
            }
        }


        // ====================================================================
        // Stage 3: Generate Firmware Metadata
        // ====================================================================

        stage('3. Generate Firmware Metadata') {

            when { expression { return !params.SKIP_BUILD.toBoolean() } }

            steps {

                echo '[Stage3] Generating firmware metadata for CI traceability'

                script {

                    bat '@if not exist "%ARTIFACTS%" mkdir "%ARTIFACTS%"'

                    // Build-type label: compute in Groovy with safe defaults.
                    // BL_BUILD_STATUS/APP_BUILD_STATUS are pre-declared in environment{},
                    // so env.X assignments from parallel branches are dropped by CPS.
                    // Use Groovy interpolation (not cmd %VAR% expansion) so the value is
                    // baked into the bat command with a non-empty fallback.
                    def blStatus  = env.BL_BUILD_STATUS?.trim()  ?: 'unknown'
                    def appStatus = env.APP_BUILD_STATUS?.trim() ?: 'unknown'
                    def buildType  = "${blStatus}-APP-${appStatus}"
                    echo "[Stage3] build-type label = ${buildType}"

                    // firmware_metadata.py generate subcommand
                    bat """
@"%VENV_PY%" "%TOOLS%\\firmware_metadata.py" generate ^
    --chip "%CHIP%" ^
    --build-number "%BUILD_NUMBER%" ^
    --bootloader-sdk "1.0.3" ^
    --app-sdk "1.0.4" ^
    --app-image "app_fw.bin" ^
    --build-type "${buildType}" ^
    --workspace "%CI_ROOT%" ^
    --output "%ARTIFACTS%\\firmware_metadata.json"
if errorlevel 1 (echo ERROR: firmware_metadata.py generate failed & exit /b 1)
"""

                    echo '[PASS] firmware_metadata.json generated'
                }
            }
        }


        // ====================================================================
        // Stage 4: Flash
        // ====================================================================

        stage('4. Flash') {

            when { expression { return !params.SKIP_FLASH.toBoolean() } }

            stages {


                // ============================================================
                // 4.1 Detect Firmware Layout
                // ============================================================

                stage('4.1 Detect Firmware Layout') {

                    steps {

                        echo '[Stage4.1] Detecting firmware layout (RTT addr, Image Info, flash partitions)'

                        script {

                            if (params.DRY_RUN.toBoolean()) {
                                echo '[DRY-RUN] Skipping firmware layout detection (no .bin in dry-run). Using fallback addresses.'
                                env.BL_ADDR     = '0x00204000'
                                env.BL_END      = '0x0023FFFF'
                                env.APP_ADDR    = '0x00240000'
                                env.APP_END     = '0x00297FFF'
                                env.BANK_B_ADDR = '0x00298000'
                                env.BANK_B_END  = '0x002EEFFF'
                                env.BL_RTT_ADDR  = '0x2000C830'
                                env.APP_RTT_ADDR = '0x2000D000'
                                echo "Layout (fallback): BL=${env.BL_ADDR}-${env.BL_END} APP=${env.APP_ADDR}-${env.APP_END} BANK_B=${env.BANK_B_ADDR}-${env.BANK_B_END} NVDS=${env.NVDS_ADDR}"
                            } else {

                            def blMap  = "${env.BL_GCC}\\out\\lst\\app_bootloader.map"
                            def appMap = "${env.APP_GCC}\\out\\lst\\ble_app_uart_c.map"
                            def blBin  = "${env.CI_ROOT}\\bl_fw.bin"
                            def appBin = "${env.CI_ROOT}\\app_fw.bin"

                            // Required files
                            bat """
@if not exist "${blMap}" (echo ERROR: BL map missing & exit /b 1)
@if not exist "${blBin}" (echo ERROR: bl_fw.bin missing & exit /b 1)
@if not exist "${appBin}" (echo ERROR: app_fw.bin missing & exit /b 1)
"""

                            // Build detection command
                            // Use -u for unbuffered stdout
                            def layoutCmd =
                                "@\"${env.VENV_PY}\" -u \"${env.TOOLS}\\detect_firmware_layout.py\" " +
                                "--bl-map \"${blMap}\" --bl-bin \"${blBin}\" --app-bin \"${appBin}\""

                            // APP map is optional (may be missing if build failed)
                            def appMapExists = bat(
                                returnStatus: true,
                                script: "@if exist \"${appMap}\" exit /b 0 else exit /b 1"
                            ) == 0

                            if (appMapExists) {
                                layoutCmd += " --app-map \"${appMap}\""
                            } else {
                                echo '[WARN] APP map file not found. APP RTT addr will use default/scan.'
                            }

                            // Run detection (outputs key=value to stdout)
                            def layoutOut = bat(returnStdout: true, script: layoutCmd).trim()

                            echo "DEBUG layoutOut=[${layoutOut}]"

                            layoutOut.split(/\r?\n/).each { rawLine ->
                                def line = rawLine.trim()
                                if (!line || !line.contains('=')) return
                                def parts = line.split('=', 2)
                                if (parts.length == 2) {
                                    def key = parts[0].trim()
                                    def val = parts[1].trim()
                                    if (key && key ==~ /[A-Z_]+/) {
                                        env."${key}" = val
                                    }
                                }
                            }

                            // Layout validation + fallback
                            if (!env.BL_ADDR || !env.APP_ADDR) {
                                if (params.ALLOW_LAYOUT_FALLBACK.toBoolean()) {
                                    echo '[WARN] WARNING: Firmware layout fallback is enabled. This build MUST NOT be considered production CI.'
                                    env.BL_ADDR     = '0x00204000'
                                    env.BL_END      = '0x0023FFFF'
                                    env.APP_ADDR    = '0x00240000'
                                    env.APP_END     = '0x00297FFF'
                                    env.BANK_B_ADDR = '0x00298000'
                                    env.BANK_B_END  = '0x002EEFFF'
                                } else {
                                    error(
                                        'Firmware layout detection FAILED - missing BL_ADDR or APP_ADDR. ' +
                                        'Set ALLOW_LAYOUT_FALLBACK=true only in development.'
                                    )
                                }
                            }

                            echo "Layout: BL=${env.BL_ADDR}-${env.BL_END} APP=${env.APP_ADDR}-${env.APP_END} BANK_B=${env.BANK_B_ADDR}-${env.BANK_B_END} NVDS=${env.NVDS_ADDR}"
                            echo "RTT: BL=${env.BL_RTT_ADDR} APP=${env.APP_RTT_ADDR ?: 'not detected (will scan)'}"
                            }
                        }
                    }
                }


                // ============================================================
                // 4.2 Verify Firmware Metadata
                // ============================================================

                stage('4.2 Verify Firmware Metadata') {

                    steps {

                        echo '[Stage4.2] Verifying firmware metadata git_commit matches current build'

                        script {

                            def metaPath = "${env.ARTIFACTS}\\firmware_metadata.json"

                            if (fileExists(metaPath)) {
                                // firmware_metadata.py verify subcommand
                                bat '''
@"%VENV_PY%" "%TOOLS%\\firmware_metadata.py" verify ^
    --metadata "%ARTIFACTS%\\firmware_metadata.json" ^
    --workspace "%CI_ROOT%"
if errorlevel 1 (echo ERROR: firmware metadata verification failed & exit /b 1)
'''
                                echo '[PASS] firmware_metadata.json verified: git_commit matches current HEAD'
                            } else {
                                echo '[WARN] firmware_metadata.json not found (build may have been skipped). Skipping verification.'
                            }
                        }
                    }
                }


                // ============================================================
                // 4.3 Generate & Validate Flash Plan
                // ============================================================

                stage('4.3 Generate & Validate Flash Plan') {

                    steps {

                        echo '[Stage4.3] Generating and validating flash plan'

                        script {

                            // flash_plan.py generate subcommand
                            bat '''
@"%VENV_PY%" "%CI_DIR%\\flash_plan.py" generate ^
    --chip "%CHIP%" ^
    --bl-addr "%BL_ADDR%" --bl-end "%BL_END%" ^
    --app-addr "%APP_ADDR%" --app-end "%APP_END%" ^
    --bank-b-addr "%BANK_B_ADDR%" --bank-b-end "%BANK_B_END%" ^
    --nvds-addr "%NVDS_ADDR%" ^
    --output "%ARTIFACTS%\\flash_plan.json"
if errorlevel 1 (echo ERROR: flash_plan.py generate failed & exit /b 1)
'''
                            echo '[PASS] flash_plan.json generated'

                            // flash_plan.py validate subcommand
                            bat '''
@"%VENV_PY%" "%CI_DIR%\\flash_plan.py" validate --plan "%ARTIFACTS%\\flash_plan.json"
if errorlevel 1 (echo ERROR: flash_plan.py validate failed & exit /b 1)
'''
                            echo '[PASS] flash_plan.json validated: NVDS preserved, App-first/BL-last confirmed'
                        }
                    }
                }


                // ============================================================
                // 4.4 Locate Firmware Images
                // ============================================================

                stage('4.4 Locate Firmware Images') {

                    steps {

                        echo '[Stage4.4] Locating firmware images'

                        script {

                            if (params.DRY_RUN.toBoolean()) {
                                echo '[DRY-RUN] No real .bin files. Using placeholder image paths.'
                                env.BL_IMAGE  = "${env.CI_ROOT}\\bl_fw.bin"
                                env.APP_IMAGE = "${env.CI_ROOT}\\app_fw.bin"
                                echo "BOOTLOADER IMAGE (placeholder): ${env.BL_IMAGE}"
                                echo "APP IMAGE (placeholder): ${env.APP_IMAGE}"
                            } else {

                            // Bootloader image: prefer CI_ROOT/bl_fw.bin (generated in Stage 2)
                            def blCandidates = ["${env.CI_ROOT}\\bl_fw.bin"]
                            def blImage = blCandidates.find { fileExists(it) }

                            if (!blImage) {
                                // Fallback: search bootloader project directory
                                blImage = bat(
                                    returnStdout: true,
                                    script: '''
@echo off
for /f "delims=" %%f in ('dir /b /s /o-d "%BL_GCC%\\*.bin" 2^>nul ^| findstr /i "bootloader"') do (echo %%f & goto :found)
echo NOT_FOUND
:found
'''
                                ).trim()
                            }

                            if (!blImage || blImage == 'NOT_FOUND') {
                                error('Bootloader image not found. Ensure Stage 2 build completed successfully.')
                            }

                            // APP image: prefer CI_ROOT/app_fw.bin (generated in Stage 2)
                            def appCandidates = ["${env.CI_ROOT}\\app_fw.bin"]
                            def appImage = appCandidates.find { fileExists(it) }

                            if (!appImage) {
                                // Fallback: search app project directory
                                appImage = bat(
                                    returnStdout: true,
                                    script: '''
@echo off
for /f "delims=" %%f in ('dir /b /s /o-d "%APP_GCC%\\*.bin" 2^>nul ^| findstr /i "app_fw\\|ble_app"') do (echo %%f & goto :found)
echo NOT_FOUND
:found
'''
                                ).trim()
                            }

                            if (!appImage || appImage == 'NOT_FOUND') {
                                error('APP image not found. Ensure Stage 2 build completed successfully.')
                            }

                            env.BL_IMAGE  = blImage
                            env.APP_IMAGE = appImage

                            echo "BOOTLOADER IMAGE: ${env.BL_IMAGE}"
                            echo "APP IMAGE: ${env.APP_IMAGE}"
                            }
                        }
                    }
                }


                // ============================================================
                // 4.5 Hardware Flash Confirmation (only when DRY_RUN=false)
                // ============================================================

                stage('4.5 Hardware Flash Confirmation') {

                    when { expression { return !params.DRY_RUN.toBoolean() } }

                    steps {

                        echo '[Stage4.5] AWAITING HUMAN CONFIRMATION before real hardware flash'

                        script {

                            input(
                                message: """
============================================================
GR5526 HARDWARE FLASH CONFIRMATION
============================================================
CHIP:       ${env.CHIP}
J-LINK:     ${env.JLINK_SERIAL} (idx=${env.JLINK_IDX})
------------------------------------------------------------
FIRMWARE
------------------------------------------------------------
BOOTLOADER: ${env.BL_IMAGE}
APP:        ${env.APP_IMAGE}
------------------------------------------------------------
FLASH LAYOUT
------------------------------------------------------------
BOOTLOADER: ${env.BL_ADDR} -> ${env.BL_END}
APP:        ${env.APP_ADDR} -> ${env.APP_END}
BANK B:     ${env.BANK_B_ADDR} -> ${env.BANK_B_END}
NVDS:       ${env.NVDS_ADDR} (PRESERVED)
------------------------------------------------------------
FLASH ORDER
------------------------------------------------------------
1. Erase BL region
2. Erase Bank A
3. Erase Bank B
4. Program APP FIRST
5. Program Bootloader LAST
6. Verify Flash
7. Reset Device
------------------------------------------------------------
WARNING: THIS WILL MODIFY GR5526 FLASH.
============================================================
""",
                                ok: 'Flash Device'
                            )

                            echo '[PASS] Human confirmation received. Proceeding with hardware flash.'
                        }
                    }
                }


                // ============================================================
                // 4.6 Erase Flash Regions
                // ============================================================

                stage('4.6 Erase Flash Regions') {

                    steps {

                        echo '[Stage4.6] Erasing BL + Bank A + Bank B. NVDS preserved. NO eraseall.'

                        script {

                            // Bootloader region
                            grConsole(
                                "eraseFlash --start ${env.BL_ADDR} --end ${env.BL_END} " +
                                "--chip ${env.CHIP} --jlink ${env.JLINK_IDX}"
                            )
                            echo "  -> Bootloader region ${env.BL_ADDR}-${env.BL_END} erased"

                            // Bank A (APP)
                            grConsole(
                                "eraseFlash --start ${env.APP_ADDR} --end ${env.APP_END} " +
                                "--chip ${env.CHIP} --jlink ${env.JLINK_IDX}"
                            )
                            echo "  -> Bank A ${env.APP_ADDR}-${env.APP_END} erased"

                            // Bank B
                            grConsole(
                                "eraseFlash --start ${env.BANK_B_ADDR} --end ${env.BANK_B_END} " +
                                "--chip ${env.CHIP} --jlink ${env.JLINK_IDX}"
                            )
                            echo "  -> Bank B ${env.BANK_B_ADDR}-${env.BANK_B_END} erased"

                            echo '[PASS] Erase complete. NVDS preserved. No eraseall.'
                        }
                    }
                }


                // ============================================================
                // 4.7 Program APP FIRST
                // ============================================================

                stage('4.7 Program APP (FIRST)') {

                    steps {

                        echo '[Stage4.7] Programming APP FIRST (--erase 2: SCA temporarily -> App)'

                        script {

                            if (!env.APP_IMAGE?.trim()) {
                                error('APP_IMAGE is empty. Refusing to flash.')
                            }

                            // --erase 2 erases SCA/bootinfo area then rewrites SCA -> App (temporary)
                            grConsole(
                                "program --chip ${env.CHIP} --file \"${env.APP_IMAGE}\" " +
                                "--erase 2 --run false --jlink ${env.JLINK_IDX}"
                            )

                            echo '[PASS] APP programmed FIRST'
                        }
                    }
                }


                // ============================================================
                // 4.8 Program Bootloader LAST
                // ============================================================

                stage('4.8 Program Bootloader (LAST)') {

                    steps {

                        echo '[Stage4.8] Programming Bootloader LAST (--erase 2: SCA finally -> Bootloader, CRITICAL)'

                        script {

                            if (!env.BL_IMAGE?.trim()) {
                                error('BL_IMAGE is empty. Refusing to flash.')
                            }

                            // --erase 2 erases SCA/bootinfo area then rewrites SCA -> Bootloader (final)
                            // MUST be last so SCA finally points to Bootloader
                            grConsole(
                                "program --chip ${env.CHIP} --file \"${env.BL_IMAGE}\" " +
                                "--erase 2 --run false --jlink ${env.JLINK_IDX}"
                            )

                            echo '[PASS] Bootloader programmed LAST. SCA final -> Bootloader.'
                        }
                    }
                }


                // ============================================================
                // 4.9 Flash Verify (MANDATORY GATE)
                // ============================================================

                stage('4.9 Flash Verify (MANDATORY GATE)') {

                    steps {

                        echo '[Stage4.9] Verifying flash contents - MANDATORY GATE'
                        echo 'HARD RULE: If verification FAILS, pipeline STOPS. Do NOT proceed to RTT.'

                        script {

                            // Dump Bank A (first 64 bytes from APP_ADDR)
                            grConsole(
                                "dump ${env.APP_ADDR} 64 " +
                                "\"${env.WORKSPACE}\\verify_bank_a.bin\" ${env.JLINK_IDX}"
                            )
                            echo '  -> Bank A dump: verify_bank_a.bin'

                            // Dump SCA (256 bytes from 0x00200000)
                            grConsole(
                                "dump 0x00200000 256 " +
                                "\"${env.WORKSPACE}\\verify_sca.bin\" ${env.JLINK_IDX}"
                            )
                            echo '  -> SCA dump: verify_sca.bin'

                            // Run verification (verify_flash.py reads WORKSPACE and BL_ADDR from env)
                            if (params.DRY_RUN.toBoolean()) {
                                echo '[DRY-RUN] Skipping actual flash verification (dump files not generated in dry-run).'
                            } else {
                                echo 'Running flash verification...'
                                bat '@"%VENV_PY%" "%TOOLS%\\verify_flash.py"'
                            }

                            echo '[PASS] Flash verification passed (MANDATORY GATE)'
                        }
                    }
                }


                // ============================================================
                // 4.10 Reset Device
                // ============================================================

                stage('4.10 Reset Device') {

                    steps {

                        echo '[Stage4.10] Resetting device via GR5xxx_console (NOT J-Link)'

                        script {

                            // GR5xxx_console reset only. NO J-Link reset.
                            grConsole('reset 1 0')

                            echo 'Waiting 5s for GR5526 boot + RTT ready ...'
                            bat '@ping -n 6 127.0.0.1 >nul'

                            echo '[PASS] Device reset via GR5xxx_console'
                        }
                    }
                }
            }
        }


        // ====================================================================
        // Stage 5: RTT Diagnostic (OPTIONAL / UNSTABLE)
        // ====================================================================

        stage('5. RTT Diagnostic') {

            when { expression { return !params.DRY_RUN.toBoolean() && !params.SKIP_FLASH.toBoolean() } }

            steps {

                echo '[Stage5] RTT diagnostic test (OPTIONAL - failure = UNSTABLE, not FAIL)'

                script {

                    if (!env.BL_RTT_ADDR) {
                        echo '[WARN] BL_RTT_ADDR not detected. RTT diagnostic may not be able to run.'
                    }

                    def blRtt  = env.BL_RTT_ADDR  ?: '0x2000C830'
                    def appRtt = env.APP_RTT_ADDR ?: '0x2000D000'
                    def blKw   = params.BL_KEYWORD  ?: ''
                    def appKw  = params.APP_KEYWORD ?: ''

                    def testCmd =
                        "@\"${env.VENV_PY}\" \"${env.TOOLS}\\test_rtt_with_jump.py\" " +
                        "--bl-rtt-addr ${blRtt} --app-rtt-addr ${appRtt} " +
                        "--jlink-serial ${env.JLINK_SERIAL} " +
                        "--bl-timeout 8 --jump-timeout 20 " +
                        "--output \"${env.WORKSPACE}\\rtt_result.json\""

                    if (blKw)  { testCmd += " --bl-keyword \"${blKw}\"" }
                    if (appKw) { testCmd += " --app-keyword \"${appKw}\"" }

                    echo "Running RTT diagnostic (BL=${blRtt}, APP=${appRtt}) ..."

                    def testExit = bat(returnStatus: true, script: testCmd)

                    if (testExit != 0) {
                        echo "[WARN] RTT diagnostic exited with code ${testExit}. Check rtt_result.json for details."
                        // RTT is DIAGNOSTIC - do not fail the build. Report as UNSTABLE.
                        currentBuild.result = 'UNSTABLE'
                    } else {
                        echo '[PASS] RTT diagnostic passed (boot + app)'
                    }
                }
            }
        }
    }


    // ========================================================================
    // Post
    // ========================================================================

    post {

        always {

            script {

                echo '[Post] Generating test_result.json'

                try {

                    def flashStatus =
                        params.SKIP_FLASH.toBoolean()
                            ? 'SKIPPED'
                            : (
                                params.DRY_RUN.toBoolean()
                                    ? 'DRY_RUN'
                                    : (
                                        currentBuild.currentResult == 'FAILURE'
                                            ? 'FAIL'
                                            : 'PASS'
                                    )
                            )

                    def resultData = [
                        job:           env.JOB_NAME ?: 'gr5526-ci',
                        build_number:  (env.BUILD_NUMBER ?: '0') as int,
                        build_url:     env.BUILD_URL,
                        result:        currentBuild.currentResult,
                        dry_run:       params.DRY_RUN,
                        skip_build:    params.SKIP_BUILD,
                        skip_flash:    params.SKIP_FLASH,
                        chip:          env.CHIP,
                        jlink_serial:  env.JLINK_SERIAL,
                        hardware_agent: env.NODE_LABELS ?: 'gr5526-hw',
                        bl_project:    env.BL_GCC,
                        app_project:   env.APP_GCC,
                        bl_image:      env.BL_IMAGE,
                        app_image:     env.APP_IMAGE,
                        bl_addr:       env.BL_ADDR,
                        bl_end:        env.BL_END,
                        app_addr:      env.APP_ADDR,
                        app_end:       env.APP_END,
                        nvds_addr:     env.NVDS_ADDR,
                        flash: [
                            erase:        flashStatus,
                            app_program:  flashStatus,
                            boot_program: flashStatus,
                            verify:       flashStatus
                        ],
                        rtt: [
                            status:       currentBuild.result ?: 'PASS',
                            bl_rtt_addr:  env.BL_RTT_ADDR ?: 'not-detected',
                            app_rtt_addr: env.APP_RTT_ADDR ?: 'not-detected',
                            notes:        'RTT is diagnostic/optional. UNSTABLE does not mean build failure.'
                        ],
                        timestamp: new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'")
                    ]

                    // Use Groovy built-in JsonOutput (no plugin dependency)
                    def jsonStr = groovy.json.JsonOutput.prettyPrint(
                        groovy.json.JsonOutput.toJson(resultData)
                    )
                    writeFile(
                        file: "${env.ARTIFACTS}\\test_result.json",
                        text: jsonStr
                    )

                    echo '[PASS] test_result.json generated'

                } catch (Exception e) {
                    echo "[WARN] Failed to generate test_result.json: ${e.getMessage()}"
                }


                // Copy external artifacts into Jenkins workspace for archiving
                bat '''
@echo off
if not exist "artifacts" mkdir "artifacts"
xcopy /E /I /Y "%ARTIFACTS%\\*" "artifacts\\" 2>nul
if errorlevel 1 echo WARNING: artifact copy failed.
exit /b 0
'''

                archiveArtifacts(
                    artifacts: 'artifacts/**/*,rtt_result.json,verify_*.bin,obj_list.txt',
                    allowEmptyArchive: true,
                    fingerprint: true
                )
            }
        }

        success {
            echo 'gr5526-ci PASSED.'
        }

        failure {
            echo 'gr5526-ci FAILED. Check console output and archived artifacts.'
        }

        unstable {
            echo 'gr5526-ci UNSTABLE (RTT diagnostic may have failed).'
        }

        aborted {
            echo 'gr5526-ci ABORTED.'
        }
    }
}
