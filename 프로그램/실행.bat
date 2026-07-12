@echo off
if "%~1"=="min" goto :run
start "" /min cmd /c "%~f0" min
exit /b

:run
cd /d %~dp0
echo 필요한 패키지를 설치하는 중입니다 (처음 실행 시 몇 분 걸릴 수 있어요)...
pip install -r requirements.txt
echo.
echo 프로그램을 실행합니다. 잠시 후 브라우저가 자동으로 열려요.
echo 이 창은 최소화된 상태로 계속 실행돼요. 완전히 끄려면 종료.bat 을 사용하세요.
streamlit run Home.py
pause
