@echo off
chcp 65001
title 旅行照片AI助手 - 生产构建

echo ========================================
echo  旅行照片AI处理工具 - 生产构建
echo ========================================
echo.

cd /d "%~dp0"

call npm run build:mp-weixin

if %errorlevel% == 0 (
    echo.
    echo ========================================
    echo  ✅ 构建成功！
    echo  导入目录: dist\build\mp-weixin
    echo ========================================
)

pause
