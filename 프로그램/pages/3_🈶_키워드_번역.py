import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from lib import translate
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="키워드 번역", page_icon="🈶", layout="wide")
render_api_key_sidebar()

st.title("🈶 키워드 한→중 번역")
st.caption("번역된 중국어 키워드로 셀러라이프 크롬 확장을 이용해 타오바오/1688에서 직접 검색하세요 (반자동 단계).")

tab1, tab2 = st.tabs(["키워드 1개씩 번역", "여러 개 한번에 번역"])

with tab1:
    keyword = st.text_input("한국어 키워드")
    if st.button("번역하기"):
        client_id = get_key("papago_client_id")
        client_secret = get_key("papago_client_secret")
        result, error = translate.translate_ko_to_zh(keyword, client_id, client_secret)
        if error:
            st.error(error)
        else:
            st.success(f"번역 결과: **{result}**")

with tab2:
    keywords_text = st.text_area("한국어 키워드를 한 줄에 하나씩 입력하세요")
    if st.button("일괄 번역하기"):
        client_id = get_key("papago_client_id")
        client_secret = get_key("papago_client_secret")
        keywords = [k.strip() for k in keywords_text.splitlines() if k.strip()]

        if not keywords:
            st.warning("번역할 키워드를 입력해주세요.")
        else:
            rows = []
            progress = st.progress(0)
            for i, kw in enumerate(keywords):
                result, error = translate.translate_ko_to_zh(kw, client_id, client_secret)
                rows.append({"한국어": kw, "중국어": result if result else "", "오류": error if error else ""})
                progress.progress((i + 1) / len(keywords))

            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("번역 결과 CSV 다운로드", data=csv, file_name="키워드_번역.csv", mime="text/csv")
