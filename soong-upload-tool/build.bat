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

pyinstaller --noconfirm "final.spec"

echo.
echo ============================================
echo   Done! Open the "dist" folder in this
echo   directory to find the new exe file.
echo ============================================
echo.
pause
