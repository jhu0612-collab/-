@echo off
cd /d %~dp0
echo 이 창은 로그 확인용이에요. 오류가 발생하면 아래 내용을 캡처해서 문의해주세요.
pip install -r requirements.txt
echo.
streamlit run Home.py
pause
