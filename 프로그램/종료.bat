@echo off
echo 프로그램을 종료하는 중입니다...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | Where-Object { $_.CommandLine -like '*streamlit*' -and $_.CommandLine -like '*Home.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo 종료했습니다. 이 창은 닫아도 됩니다.
pause
