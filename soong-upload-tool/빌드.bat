@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   슝 업로드용 프로그램 다시 만들기
echo ============================================
echo.
echo 필요한 프로그램을 설치하는 중입니다... (처음 한 번만 시간이 걸려요)
echo.

python -m pip install --upgrade pip pyinstaller openpyxl requests pillow >nul 2>&1

if errorlevel 1 (
    echo.
    echo [오류] python 명령을 찾을 수 없습니다.
    echo 이 PC에 파이썬이 설치되어 있는지 확인해주세요.
    echo.
    pause
    exit /b 1
)

echo 설치 완료. 이제 exe 파일을 만듭니다...
echo.

pyinstaller --noconfirm 슝_업로드용_final.spec

echo.
echo ============================================
echo   완료되었습니다!
echo   이 폴더 안의 "dist" 폴더를 열어보세요.
echo   그 안에 새로운 exe 파일이 생겼을 거예요.
echo ============================================
echo.
pause
