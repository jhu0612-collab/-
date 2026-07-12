#!/bin/bash
cd "$(dirname "$0")"
echo "필요한 패키지를 설치하는 중입니다 (처음 실행 시 몇 분 걸릴 수 있어요)..."
pip3 install -r requirements.txt
echo ""
echo "프로그램을 실행합니다. 잠시 후 브라우저가 자동으로 열려요."
streamlit run Home.py
