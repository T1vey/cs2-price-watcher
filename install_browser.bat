@echo off
chcp 65001 >nul
echo ============================================
echo   CS2 Price Watcher - 首次安装
echo ============================================
echo.
echo 正在安装悠悠有品浏览器组件...
echo （约 110MB，只需装一次）
echo.
python -m playwright install chromium
echo.
echo 安装完成！双击 CS2-PriceWatcher.exe 即可使用。
echo.
pause
