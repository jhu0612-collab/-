@echo off
cd /d "%~dp0"

echo ============================================
echo   Rebuilding the Soong Upload Tool
echo ============================================
echo.
echo Installing required packages, please wait...
echo.

python -m pip install --upgrade pip pyinstaller openpyxl requests pillow

if errorlevel 1 (
    echo.
    echo [ERROR] Could not run "python". Is Python installed on this PC?
    echo.
    pause
    exit /b 1
)

echo.
echo Packages ready. Building the exe now...
echo.

python -m PyInstaller --noconfirm "final.spec"

echo.
echo ============================================
echo   Done! Open this folder:
echo     dist\soong_upload_final\
echo   The exe is inside THAT folder. Make a
echo   shortcut to it if you want it on your
echo   Desktop - do not move just the exe by
echo   itself, it needs the other files next
echo   to it.
echo ============================================
echo.
pause
