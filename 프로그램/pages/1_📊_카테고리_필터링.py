import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from lib import rules
from lib.state import render_api_key_sidebar

st.set_page_config(page_title="카테고리 필터링", page_icon="📊", layout="wide")
render_api_key_sidebar()

st.title("📊 카테고리/키워드 필터링")
st.caption("셀러라이프에서 다운로드한 엑셀을 올리면 강의 기준 필터를 자동 적용해요.")

st.subheader("필터 조건 (필요하면 조정하세요)")
col1, col2, col3, col4 = st.columns(4)
with col1:
    min_search = st.number_input("최소 검색량", value=rules.DEFAULT_MIN_SEARCH, step=100)
with col2:
    max_search = st.number_input("최대 검색량", value=rules.DEFAULT_MAX_SEARCH, step=100)
with col3:
    min_ratio = st.number_input(
        "최소 해외배송비율", value=rules.DEFAULT_MIN_OVERSEAS_SHIPPING_RATIO, step=0.05, format="%.2f"
    )
with col4:
    min_review = st.number_input("최소 해외배송 평균리뷰", value=rules.DEFAULT_MIN_OVERSEAS_REVIEW_AVG, step=1)

exclude_brand = st.checkbox("브랜드 키워드 제외", value=True)

uploaded = st.file_uploader("셀러라이프 엑셀 업로드 (.xlsx)", type=["xlsx"])

if uploaded is not None:
    try:
        df = pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"엑셀을 읽는 중 오류가 발생했어요: {e}")
        st.stop()

    df = rules.normalize_columns(df)
    missing = rules.check_columns(df)
    if missing:
        st.error(f"엑셀에 다음 컬럼이 없어서 필터링할 수 없어요: {missing}")
        st.info("셀러라이프 원본 포맷 그대로 업로드했는지 확인해주세요.")
        st.stop()

    st.success(f"엑셀 로드 완료: 총 {len(df):,}행")

    filtered = rules.filter_candidates(
        df,
        min_search=min_search,
        max_search=max_search,
        min_overseas_ratio=min_ratio,
        min_overseas_review_avg=min_review,
        exclude_brand=exclude_brand,
    )

    st.subheader(f"필터링 결과: {len(filtered):,}개 후보")
    display_cols = [
        c
        for c in [
            "키워드",
            "카테고리",
            "브랜드키워드",
            "최근1개월검색량",
            "계절성",
            "네이버경쟁강도",
            "쿠팡해외배송비율",
            "쿠팡해외배송평균리뷰수",
        ]
        if c in filtered.columns
    ]
    st.dataframe(filtered[display_cols], use_container_width=True)

    st.session_state["filtered_candidates"] = filtered

    csv = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button("필터링 결과 CSV 다운로드", data=csv, file_name="필터링_후보.csv", mime="text/csv")

    st.info("이 결과는 세션에 저장돼서 '🤖 AI 카테고리 추천' 페이지에서 바로 이어서 쓸 수 있어요.")
else:
    st.info("엑셀 파일을 올리면 결과가 여기 표시돼요.")
