import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st

from lib import margin
from lib.exchange import get_cny_exchange_rate
from lib.shipping import PACKAGING_TYPES
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="마진·가격 계산기", page_icon="💰", layout="wide")
render_api_key_sidebar()

st.title("💰 마진·가격 계산기")
st.caption("원가(위안)와 무게를 넣으면 환율 + 동백국제물류 배송비 + 마진을 반영한 최종 판매가를 계산해요.")
st.caption("배송비는 마진율(%)이 아니라 정액으로 최종가에 더해요 (강의 원칙 반영, 픽투셀 '추가마진' 방식과 동일).")

tab1, tab2 = st.tabs(["상품 1개씩 계산", "여러 상품 한번에 계산 (엑셀)"])


def resolve_exchange_rate(manual_rate):
    if manual_rate:
        return manual_rate, "수동입력"
    auth_key = get_key("eximbank_api_key")
    rate, info = get_cny_exchange_rate(auth_key)
    if rate is None:
        st.warning(info)
        return None, None
    return rate, f"자동조회 ({info} 기준)"


with tab1:
    col1, col2 = st.columns(2)
    with col1:
        cost_cny = st.number_input("원가 (위안/CNY)", min_value=0.0, value=100.0, step=1.0)
        weight_kg = st.number_input("무게 (kg)", min_value=0.0, value=1.0, step=0.1)
        girth_cm = st.number_input("삼변합 가로+세로+높이 (cm, 없으면 0)", min_value=0.0, value=0.0, step=1.0)
        shipping_method = st.selectbox("배송방식", ["해운", "항공"])
        packaging_type = st.selectbox("포장방식", list(PACKAGING_TYPES.keys()))
    with col2:
        margin_rate = st.number_input("마진율", min_value=0.0, value=margin.DEFAULT_MARGIN_RATE, step=0.05, format="%.2f")
        extra_margin = st.number_input("추가마진 (정액, 원)", min_value=0, value=margin.DEFAULT_EXTRA_MARGIN, step=1000)
        manual_rate = st.number_input("환율 수동입력 (0이면 자동조회 시도)", min_value=0.0, value=0.0, step=0.1)

    if st.button("계산하기", type="primary"):
        rate, rate_info = resolve_exchange_rate(manual_rate if manual_rate > 0 else None)
        if rate is None:
            st.stop()

        result = margin.calculate_final_price(
            cost_cny=cost_cny,
            exchange_rate=rate,
            weight_kg=weight_kg,
            girth_cm=girth_cm if girth_cm > 0 else None,
            shipping_method=shipping_method,
            packaging_type=packaging_type,
            margin_rate=margin_rate,
            extra_margin=extra_margin,
        )

        st.success(f"적용 환율: {rate} ({rate_info})")

        c1, c2, c3 = st.columns(3)
        c1.metric("원가(원)", f"{result['원가(원)']:,}원")
        c2.metric("배송비 합계", f"{result['배송비상세']['배송비합계']:,}원")
        c3.metric("최종 판매가", f"{result['최종판매가']:,}원")

        with st.expander("상세 내역 보기"):
            st.json(result)

with tab2:
    st.write("엑셀 컬럼: `상품명, 원가위안, 무게kg, 삼변합cm(선택), 포장방식(선택)`")
    uploaded = st.file_uploader("상품 목록 엑셀 업로드", type=["xlsx"], key="bulk_upload")
    manual_rate_bulk = st.number_input("환율 수동입력 (0이면 자동조회 시도)", min_value=0.0, value=0.0, step=0.1, key="bulk_rate")
    margin_rate_bulk = st.number_input("마진율", min_value=0.0, value=margin.DEFAULT_MARGIN_RATE, step=0.05, format="%.2f", key="bulk_margin")
    extra_margin_bulk = st.number_input(
        "추가마진 (정액, 원)", min_value=0, value=margin.DEFAULT_EXTRA_MARGIN, step=1000, key="bulk_extra"
    )

    if uploaded is not None and st.button("일괄 계산하기"):
        df = pd.read_excel(uploaded)
        required = ["상품명", "원가위안", "무게kg"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            st.error(f"엑셀에 다음 컬럼이 없어요: {missing}")
            st.stop()

        rate, rate_info = resolve_exchange_rate(manual_rate_bulk if manual_rate_bulk > 0 else None)
        if rate is None:
            st.stop()
        st.info(f"적용 환율: {rate} ({rate_info})")

        rows = []
        for _, row in df.iterrows():
            girth = row.get("삼변합cm", None)
            packaging = row.get("포장방식", "일반")
            result = margin.calculate_final_price(
                cost_cny=row["원가위안"],
                exchange_rate=rate,
                weight_kg=row["무게kg"],
                girth_cm=girth if girth and girth > 0 else None,
                packaging_type=packaging if packaging in PACKAGING_TYPES else "일반",
                margin_rate=margin_rate_bulk,
                extra_margin=extra_margin_bulk,
            )
            rows.append(
                {
                    "상품명": row["상품명"],
                    "원가(위안)": row["원가위안"],
                    "원가(원)": result["원가(원)"],
                    "배송비": result["배송비상세"]["배송비합계"],
                    "최종판매가": result["최종판매가"],
                }
            )

        result_df = pd.DataFrame(rows)
        st.dataframe(result_df, use_container_width=True)
        csv = result_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("계산 결과 CSV 다운로드", data=csv, file_name="마진계산_결과.csv", mime="text/csv")
