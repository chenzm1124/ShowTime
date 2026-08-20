@echo off
chcp 65001
title 旅行照片AI助手 - 开发模式

echo ========================================
echo  旅行照片AI处理工具 - 微信小程序开发模式
echo ========================================
echo.

cd /d "%~dp0"

echo [1/2] 检查依赖...
if not exist "node_modules" (
    echo 未找到 node_modules，开始安装依赖...
    call npm install
)

echo.
echo [2/2] 启动开发模式...
echo.
echo 提示：
echo 1. 编译完成后，导入 dist\dev\mp-weixin 目录到微信开发者工具
echo 2. 不要关闭此窗口，否则热更新会停止
echo.

call npm run dev:mp-weixin

pause
