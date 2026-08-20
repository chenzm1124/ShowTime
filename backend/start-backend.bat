@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ============================================================
echo  途吖后端 - 一键启动脚本
echo  自动检测 PostgreSQL -> 建库 -> 跑 seed -> 启动 uvicorn
echo ============================================================
echo.

cd /d "%~dp0"

REM ------------------------------------------------------------
REM Step 1: 检查 5432 端口是否已经在监听
REM ------------------------------------------------------------
echo [1/5] 检查 PostgreSQL (5432 端口) ...
netstat -ano | findstr :5432 | findstr LISTENING >nul 2>&1
if %ERRORLEVEL%==0 (
    echo   OK - 5432 端口已在监听
    goto :db_ready
)

echo   5432 未监听，尝试启动 PostgreSQL 服务...

REM ------------------------------------------------------------
REM Step 2: 尝试启动已装的 PG 服务（Win10/11 常见路径）
REM ------------------------------------------------------------
set "PG_SERVICE="
for %%S in (postgresql-x64-16 postgresql-x64-15 postgresql-x64-14 PostgreSQL) do (
    sc query "%%S" >nul 2>&1
    if !ERRORLEVEL!==0 set "PG_SERVICE=%%S"
)

if not "!PG_SERVICE!"=="" (
    echo   找到服务: !PG_SERVICE!，正在启动 ...
    net start "!PG_SERVICE!" >nul 2>&1
    timeout /t 3 /nobreak >nul
    netstat -ano | findstr :5432 | findstr LISTENING >nul 2>&1
    if !ERRORLEVEL!==0 (
        echo   OK - PostgreSQL 服务已启动
        goto :db_ready
    )
)

REM ------------------------------------------------------------
REM Step 3: PG 装了但没注册服务 - 找 pg_ctl
REM ------------------------------------------------------------
echo   未找到已注册的 PG 服务，尝试找 pg_ctl.exe ...
set "PG_BIN="
for /d %%D in ("C:\Program Files\PostgreSQL\*") do (
    if exist "%%D\bin\pg_ctl.exe" set "PG_BIN=%%D\bin"
)
if "!PG_BIN!"=="" for /d %%D in ("C:\Program Files (x86)\PostgreSQL\*") do (
    if exist "%%D\bin\pg_ctl.exe" set "PG_BIN=%%D\bin"
)

if not "!PG_BIN!"=="" (
    echo   找到 PG: !PG_BIN!
    REM 找数据目录（用默认的）
    set "PG_DATA=!PG_BIN!\..\data"
    if not exist "!PG_DATA!" set "PG_DATA=C:\Program Files\PostgreSQL\16\data"

    if exist "!PG_DATA!\PG_VERSION" (
        echo   数据目录存在，尝试启动 ...
        "!PG_BIN!\pg_ctl.exe" -D "!PG_DATA!" start >nul 2>&1
        timeout /t 4 /nobreak >nul
        netstat -ano | findstr :5432 | findstr LISTENING >nul 2>&1
        if !ERRORLEVEL!==0 (
            echo   OK - PostgreSQL 已启动（pg_ctl）
            set "PATH=!PG_BIN!;!PATH!"
            goto :db_ready
        )
    ) else (
        echo   数据目录不存在，需要 initdb ...
        "!PG_BIN!\initdb.exe" -D "!PG_DATA!" -U postgres --auth-host=trust --auth-local=trust >nul 2>&1
        "!PG_BIN!\pg_ctl.exe" -D "!PG_DATA!" -l "!PG_DATA!\logfile" start >nul 2>&1
        timeout /t 4 /nobreak >nul
        set "PATH=!PG_BIN!;!PATH!"
    )
) else (
    echo   ============================================
    echo   本机未检测到 PostgreSQL
    echo   ============================================
    echo.
    echo   请选择安装方式：
    echo   [1] winget 一键装（推荐，需联网）
    echo   [2] 跳过后端，先验证前端
    echo.
    set /p INSTALL_CHOICE=请输入选择 (1/2):

    if "!INSTALL_CHOICE!"=="1" (
        echo   正在用 winget 装 PostgreSQL 16 ...
        echo   （首次装可能需要几分钟 + 管理员权限）
        winget install --id PostgreSQL.PostgreSQL.16 -e --source winget --accept-package-agreements --accept-source-agreements
        if !ERRORLEVEL! NEQ 0 (
            echo   winget 装失败，请尝试 choco: choco install postgresql16
            pause
            exit /b 1
        )
        echo   winget 安装完成，请重新运行此脚本（确保环境变量刷新）
        pause
        exit /b 0
    ) else (
        echo   已跳过 PostgreSQL 安装
        echo   注意：前端将无法获取真实 /vip/plans 数据
        echo   是否仍要启动后端（mock 模式，无 DB）? [y/N]
        set /p SKIP_DB=
        if /i "!SKIP_DB!"=="y" (
            set "ENABLE_MOCK_MODE=true"
            goto :start_uvicorn
        ) else (
            pause
            exit /b 1
        )
    )
)

:db_ready
REM ------------------------------------------------------------
REM Step 4: 建库 + 跑 seed
REM ------------------------------------------------------------
echo.
echo [2/5] 建数据库（如已存在则跳过）...
where psql >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo   psql 不在 PATH 里，尝试用 PG 安装目录的 psql
    for /d %%D in ("C:\Program Files\PostgreSQL\*") do (
        if exist "%%D\bin\psql.exe" set "PATH=%%D\bin;!PATH!"
    )
)

REM 默认账号/密码/库名（来自 docker-compose.yml）
set "DB_USER=travelphoto"
set "DB_PASS=travelphoto"
set "DB_NAME=travelphoto"

REM 优先用 postgres 超级用户建库 + 角色（首次）
psql -U postgres -d postgres -c "SELECT 1" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo   使用 postgres 超级用户 ...
    psql -U postgres -d postgres -c "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname='%DB_USER%') THEN CREATE ROLE %DB_USER% LOGIN PASSWORD '%DB_PASS%'; END IF; END \$\$;" >nul 2>&1
    psql -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='%DB_NAME%'" | findstr /r "^1$" >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        psql -U postgres -d postgres -c "CREATE DATABASE %DB_NAME% OWNER %DB_USER%;" >nul 2>&1
    )
    if %ERRORLEVEL%==0 echo   OK - 数据库已就绪
) else (
    echo   postgres 超级用户连不上，尝试用 travelphoto 直接连 ...
    psql -U %DB_USER% -d %DB_NAME% -c "SELECT 1" >nul 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo   警告: 数据库未就绪，seed 可能会失败
        echo   如需手动建库，请以 postgres 身份执行：
        echo     CREATE ROLE travelphoto LOGIN PASSWORD 'travelphoto';
        echo     CREATE DATABASE travelphoto OWNER travelphoto;
    ) else (
        echo   OK - 数据库已就绪
    )
)

echo.
echo [3/5] 建表 + 跑 seed 数据 ...
echo   用 init_db.py 一把搞定（建表 + 写 VIP/次数包/测试用户）
python -m scripts.init_db --use-metadata --seed
if %ERRORLEVEL% NEQ 0 (
    echo   警告: init_db 失败，但继续启动后端 ...
    echo   可手动重试: python -m scripts.init_db --drop --use-metadata --seed
)

:start_uvicorn
REM ------------------------------------------------------------
REM Step 5: 启动 uvicorn
REM ------------------------------------------------------------
echo.
echo [4/5] 检查依赖 ...
python -c "import uvicorn, fastapi" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo   缺少依赖，正在装 ...
    python -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo [5/5] 启动后端服务
echo   访问 http://localhost:8000/api/v1/packs 测试（次数套餐包）
echo   访问 http://localhost:8000/docs 查看 API 文档
echo   Ctrl+C 停止
echo ============================================================
echo.

set PYTHONIOENCODING=utf-8
python -m uvicorn app.main:app --reload --port 8000

pause
