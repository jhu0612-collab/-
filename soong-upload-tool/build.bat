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
echo   Done! Find the new exe here:
echo     dist\soong_upload_final.exe
echo   This single file can be copied and
echo   shared anywhere on its own.
echo ============================================
echo.
pause
