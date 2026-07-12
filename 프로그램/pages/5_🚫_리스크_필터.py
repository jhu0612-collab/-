import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from lib import rules
from lib.state import render_api_key_sidebar

st.set_page_config(page_title="리스크 필터", page_icon="🚫", layout="wide")
render_api_key_sidebar()

st.title("🚫 지재권/통관 리스크 필터")
st.caption("상품명·카테고리에 지재권 위험 브랜드나 목록통관 배제 품목 키워드가 있는지 체크해요.")

tab1, tab2, tab3 = st.tabs(["텍스트로 체크", "여러 개 한번에 체크", "블랙리스트 관리"])

with tab1:
    text = st.text_input("상품명 또는 카테고리 입력")
    if st.button("체크하기"):
        reasons = rules.check_risk(text)
        if reasons:
            st.error("위험 항목 발견:")
            for r in reasons:
                st.write(f"- {r}")
        else:
            st.success("블랙리스트/통관배제 키워드가 발견되지 않았어요. (실제 통관 여부는 별도 확인 필요)")

with tab2:
    text_area = st.text_area("상품명을 한 줄에 하나씩 입력하세요")
    if st.button("일괄 체크하기"):
        items = [(line.strip(), line.strip()) for line in text_area.splitlines() if line.strip()]
        if not items:
            st.warning("입력된 항목이 없어요.")
        else:
            df = rules.check_risk_bulk(items)
            st.dataframe(df, use_container_width=True)
            danger_count = (df["위험여부"] == "위험").sum()
            st.info(f"총 {len(df)}개 중 {danger_count}개 위험 항목 발견")
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("체크 결과 CSV 다운로드", data=csv, file_name="리스크_체크_결과.csv", mime="text/csv")

with tab3:
    st.write("블랙리스트/통관배제 키워드는 아래 파일을 직접 수정해서 관리해요.")
    st.code(f"data/blacklist.txt\ndata/customs_excluded.txt")

    st.subheader("현재 지재권 블랙리스트")
    st.write(", ".join(rules.load_blacklist()))

    st.subheader("현재 목록통관 배제 키워드")
    st.write(", ".join(rules.load_customs_excluded()))

    st.info("텍스트 파일을 메모장으로 열어서 한 줄에 하나씩 추가/삭제하면 바로 반영돼요 (프로그램 재시작 필요).")
