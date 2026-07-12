import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st

from lib import ai
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="AI 카테고리 추천", page_icon="🤖", layout="wide")
render_api_key_sidebar()

st.title("🤖 AI 2차 카테고리 추천")
st.caption("1번 페이지에서 필터링한 후보 중, 계절성·트렌드까지 고려한 최종 추천을 AI에게 받아요.")

filtered = st.session_state.get("filtered_candidates")

if filtered is None or len(filtered) == 0:
    st.warning("먼저 '📊 카테고리 필터링' 페이지에서 엑셀을 업로드하고 필터링을 실행해주세요.")
    st.stop()

st.write(f"현재 세션에 저장된 후보: {len(filtered):,}개")

top_n = st.slider("추천받을 개수", min_value=3, max_value=30, value=10)
max_candidates = st.slider("AI에게 보여줄 후보 수 (검색량 높은 순, 너무 많으면 비용/시간 증가)", 10, 300, 100)

if st.button("AI 추천 받기", type="primary"):
    api_key = get_key("anthropic_api_key")
    with st.spinner("AI가 후보를 분석하는 중이에요..."):
        result, error = ai.recommend_categories(api_key, filtered, top_n=top_n, max_candidates=max_candidates)

    if error:
        st.error(error)
    else:
        st.markdown(result)
