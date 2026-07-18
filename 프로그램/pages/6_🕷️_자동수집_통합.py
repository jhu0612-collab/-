import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

import pandas as pd
import streamlit as st

from lib import ai, apify_scraper, archive, category_code, rules
from lib import shipping as shipping_calc
from lib.pick2sell_export import export_to_pick2sell_template
from lib.shipping import PACKAGING_TYPES
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="자동수집 통합", page_icon="🕷️", layout="wide")
render_api_key_sidebar()

st.title("🕷️ 타오바오 자동수집 → 마진계산 → 픽투셀 양식 출력")
st.caption("키워드 하나로 검색부터 픽투셀 업로드용 엑셀까지 한번에 처리해요. (Apify API 토큰 필요)")

def _auto_match_categories(korean_keyword, anthropic_key):
    results = {}
    for system in ["쿠팡", "스스"]:
        candidates = category_code.find_candidates(korean_keyword, system=system)
        if not candidates:
            results[system] = (None, "후보 카테고리를 못 찾았어요.")
            continue
        code, error = ai.match_category_code(anthropic_key, korean_keyword, candidates)
        if error:
            results[system] = (None, error)
        else:
            path = dict(candidates)[code]
            st.session_state[f"matched_category_{system}"] = code
            results[system] = (code, path)
    return results


st.markdown("### 🔍 검색 및 수집")

col1, col2, col3, col4 = st.columns(4)
with col1:
    keyword = st.text_input(
        "검색 키워드 (중국어)",
        value=st.session_state.get("last_chinese_keyword", ""),
        help="왼쪽 사이드바의 '🈶 키워드 번역' 페이지에서 번역하면 자동으로 채워져요. 직접 입력해도 돼요.",
    )
with col2:
    min_price = st.number_input("최저가 (위안)", min_value=0.0, value=0.0, step=1.0)
with col3:
    max_price = st.number_input("최고가 (위안)", min_value=0.0, value=300.0, step=1.0)
with col4:
    max_items = st.number_input("최대 수집 개수 (최소 10)", min_value=10, max_value=500, value=50, step=10)

st.caption("💡 카테고리 코드 자동매칭용 한국어 키워드도 왼쪽 사이드바 '🈶 키워드 번역' 페이지에서 입력한 게 자동으로 같이 넘어와요.")

tmall_only = st.checkbox("티몰(정품 브랜드관)만 검색", value=False)

if st.button("타오바오 검색·수집 실행", type="primary"):
    api_token = get_key("apify_api_token")
    with st.spinner("Apify에서 타오바오를 검색하는 중이에요..."):
        items, error = apify_scraper.search_products(
            api_token,
            keyword,
            min_price=min_price if min_price > 0 else None,
            max_price=max_price if max_price > 0 else None,
            max_items=int(max_items),
            tmall_only=tmall_only,
        )
    if error:
        st.error(error)
    elif not items:
        st.warning("검색 결과가 없어요. 키워드나 가격범위를 확인해보세요.")
    else:
        rows = apify_scraper.to_rows(items)
        df = pd.DataFrame(rows)

        archived_urls = archive.get_archived_urls()
        before_count = len(df)
        df = df[~df["URL"].isin(archived_urls)].reset_index(drop=True)
        dup_count = before_count - len(df)

        df["예상무게(kg)"] = 1.0
        st.session_state["scraped_df"] = df
        st.session_state["scraped_keyword"] = keyword

        korean_kw = st.session_state.get("last_korean_keyword", "")
        st.session_state["scraped_korean_keyword"] = korean_kw

        if dup_count > 0:
            st.info(f"이전에 이미 처리한 상품 {dup_count}개는 자동으로 제외했어요.")
        st.success(f"{len(df)}개 상품 수집 완료! (신규 상품 기준)")

        if korean_kw:
            anthropic_key = get_key("anthropic_api_key")
            with st.spinner("쿠팡·스스 카테고리 코드 자동매칭 중..."):
                results = _auto_match_categories(korean_kw, anthropic_key)
            for system, (code, info) in results.items():
                if code:
                    st.info(f"[{system} 카테고리 자동매칭] {code} → {info}")
                else:
                    st.warning(f"[{system} 카테고리 자동매칭 실패] {info} (3단계에서 직접 입력하면 돼요)")
        else:
            st.caption("한국어 키워드가 없어서 카테고리 자동매칭은 건너뛰었어요. 3단계에서 직접 입력할 수 있어요.")

if "scraped_df" in st.session_state:
    st.markdown("### ⚖️ 무게 확인 및 배송비(추가마진) 계산")
    st.caption(
        "타오바오 검색결과엔 무게 정보가 없어서, 예상무게를 직접 입력/수정해야 해요 (대충 추산해서 넣으면 돼요). "
        "원가×마진율 계산은 픽투셀이 자체 설정대로 알아서 하고, 저희는 무게 기준 배송비만 계산해서 '추가마진'에 얹어요."
    )

    if st.button("🤖 AI로 상품별 무게 자동추산", type="primary"):
        anthropic_key = get_key("anthropic_api_key")
        titles = st.session_state["scraped_df"]["상품명"].tolist()
        with st.spinner("AI가 상품명을 보고 종류별로 무게를 추산하는 중이에요..."):
            weights, error = ai.estimate_weights(anthropic_key, titles)
        if error:
            st.error(error)
        else:
            st.session_state["scraped_df"]["예상무게(kg)"] = [shipping_calc.round_up_to_half_kg(w) for w in weights]
            st.success("AI 추산 완료! 참고용이니 아래 표에서 확인하고 이상하면 직접 고치세요.")
            st.rerun()

    bulk_col1, bulk_col2 = st.columns([1, 3])
    with bulk_col1:
        bulk_weight = st.number_input("전체 동일 무게로 일괄 적용(kg)", min_value=0.0, value=1.0, step=0.1)
    with bulk_col2:
        st.write("")
        if st.button("⬆ 위 무게를 전체 상품에 한번에 적용"):
            st.session_state["scraped_df"]["예상무게(kg)"] = shipping_calc.round_up_to_half_kg(bulk_weight)
            st.rerun()
    st.caption(
        "전 상품이 다 비슷한 무게면 일괄적용, 상품마다 다르면 AI 추산 후 표에서 미세조정하세요. "
        "동백 요금이 0.5kg 단위로 끊어 청구돼서, 무게는 항상 0.5kg 단위로 올림해서 표시돼요 (예: 0.8→1.0, 1.1→1.5)."
    )

    edited_df = st.data_editor(
        st.session_state["scraped_df"],
        use_container_width=True,
        num_rows="fixed",
        key="scraped_editor",
    )
    st.session_state["scraped_df"] = edited_df

    c1, c2, c3 = st.columns(3)
    with c1:
        shipping_method = st.selectbox("배송방식", ["해운", "항공"])
    with c2:
        packaging_type = st.selectbox("포장방식", list(PACKAGING_TYPES.keys()))
    with c3:
        extra_margin_base = st.number_input(
            "배송비 외 기본 추가마진(정액,원)", min_value=0, value=10000, step=1000,
            help="배송비에 더해서 얹을 고정금액이에요. 최종 추가마진 = 이 값 + 무게 기준 배송비.",
        )

    if st.button("배송비 계산 + 리스크체크 실행", type="primary"):
        result_rows = []
        for _, row in edited_df.iterrows():
            if pd.isna(row["원가위안"]):
                continue
            billed_weight = shipping_calc.round_up_to_half_kg(row["예상무게(kg)"])
            shipping = shipping_calc.calculate_shipping(
                weight_kg=billed_weight,
                shipping_method=shipping_method,
                packaging_type=packaging_type,
            )
            reasons = rules.check_risk(row["상품명"] or "")
            result_rows.append(
                {
                    "상품명": row["상품명"],
                    "URL": row["URL"],
                    "원가위안": row["원가위안"],
                    "예상무게(kg)": billed_weight,
                    "배송비": shipping["배송비합계"],
                    "추가마진": shipping["배송비합계"] + extra_margin_base,
                    "위험여부": "위험" if reasons else "안전",
                    "위험사유": " / ".join(reasons),
                }
            )
        st.session_state["priced_df"] = pd.DataFrame(result_rows)

if "priced_df" in st.session_state:
    st.markdown("### 📤 최종 확인 및 픽투셀 양식 다운로드")
    priced_df = st.session_state["priced_df"]
    st.dataframe(priced_df, use_container_width=True)

    exclude_risky = st.checkbox("위험 상품은 제외하고 내보내기", value=True)

    export_df = priced_df[priced_df["위험여부"] == "안전"] if exclude_risky else priced_df
    st.write(f"내보낼 상품 수: {len(export_df)}개 (픽투셀 파일 1개당 최대 500개)")

    st.markdown("#### 카테고리 코드 (1단계에서 자동으로 매칭됨)")
    st.caption("검색할 때 자동으로 매칭돼서 아래 채워져 있어요. 틀렸으면 직접 고치면 돼요 (픽투셀은 둘 다 있으면 쿠팡 기준으로 매칭).")

    c1, c2 = st.columns(2)
    with c1:
        category_code_coupang = st.text_input("쿠팡 카테고리 코드", value=st.session_state.get("matched_category_쿠팡", ""))
    with c2:
        category_code_ss = st.text_input("스스 카테고리 코드", value=st.session_state.get("matched_category_스스", ""))

    if st.button("카테고리 코드 다시 매칭"):
        korean_kw = st.session_state.get("scraped_korean_keyword", "")
        if not korean_kw:
            st.warning("한국어 키워드가 없어요. 왼쪽 사이드바의 '🈶 키워드 번역' 페이지에서 먼저 번역해주세요.")
        else:
            anthropic_key = get_key("anthropic_api_key")
            with st.spinner("다시 매칭하는 중..."):
                results = _auto_match_categories(korean_kw, anthropic_key)
            for system, (code, info) in results.items():
                if code:
                    st.success(f"[{system}] {code} → {info}")
                else:
                    st.error(f"[{system}] {info}")
            st.rerun()

    if st.button("픽투셀 양식 엑셀 만들기", type="primary"):
        if len(export_df) == 0:
            st.warning("내보낼 상품이 없어요.")
        else:
            rows = [
                {
                    "url": r["URL"],
                    "title": r["상품명"],
                    "category_code_coupang": category_code_coupang,
                    "category_code_ss": category_code_ss,
                    "extra_margin": r["추가마진"],
                    "memo": r["위험사유"] if not exclude_risky and r["위험여부"] == "위험" else "",
                }
                for _, r in export_df.iterrows()
            ]
            tmp_path = os.path.join(tempfile.gettempdir(), "픽투셀_업로드용.xlsx")
            try:
                export_to_pick2sell_template(rows, tmp_path)
                archive.add_to_archive(rows, keyword=st.session_state.get("scraped_keyword"))
                with open(tmp_path, "rb") as f:
                    st.download_button(
                        "픽투셀 업로드용 엑셀 다운로드",
                        data=f.read(),
                        file_name="픽투셀_업로드용.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                st.success(f"이 파일을 픽투셀 '엑셀로 일괄등록' 화면에 그대로 올리면 돼요. ({len(rows)}개 아카이브에 기록됨)")
            except Exception as e:
                st.error(f"엑셀 생성 실패: {e}")

st.markdown("---")
with st.expander("📦 아카이브 관리"):
    archived_count = len(archive.get_archived_urls())
    st.write(f"지금까지 픽투셀로 내보낸 상품: **{archived_count:,}개** (다음 수집 때 자동으로 중복 제외돼요)")
    if st.button("아카이브 초기화 (중복제외 기록 삭제)"):
        archive.clear_archive()
        st.success("아카이브를 초기화했어요.")
        st.rerun()
