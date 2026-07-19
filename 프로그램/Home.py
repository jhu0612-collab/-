import os
import tempfile

import pandas as pd
import streamlit as st

from lib import ai, apify_scraper, archive, category_code, rules, translate
from lib import shipping as shipping_calc
from lib.pick2sell_export import export_to_pick2sell_template
from lib.shipping import PACKAGING_TYPES
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="해구대 소싱 자동화", page_icon="📦", layout="wide")
render_api_key_sidebar()

st.title("📦 해구대 소싱 자동화 도구")
st.caption("키워드 하나로 번역 → 검색·수집 → 무게·배송비 계산 → 카테고리 매칭 → 픽투셀 업로드용 엑셀까지 한 화면에서 처리해요.")


def _auto_match_categories(korean_keyword, anthropic_key):
    """반환값: {system: (code, 설명, 추정여부)}. 부분단어로도 못 찾으면 대분류부터 추정해서라도 채운다."""
    results = {}
    for system in ["쿠팡", "스스"]:
        candidates = category_code.find_candidates(korean_keyword, system=system)
        if candidates:
            code, error = ai.match_category_code(anthropic_key, korean_keyword, candidates)
            if error:
                results[system] = (None, error, False)
            else:
                path = dict(candidates)[code]
                st.session_state[f"matched_category_{system}"] = code
                results[system] = (code, path, False)
        else:
            code, info = ai.guess_category_fallback(anthropic_key, korean_keyword, system)
            if code:
                st.session_state[f"matched_category_{system}"] = code
                results[system] = (code, info, True)
            else:
                results[system] = (None, info, False)
    return results


with st.expander("📊 카테고리 후보 찾기 (선택) — 셀러라이프 엑셀로 키워드 발굴"):
    st.caption("검색할 키워드가 이미 정해져 있으면 건너뛰어도 돼요. 아래에서 찾은 키워드를 밑에 직접 입력하면 돼요.")

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
            filter_df = pd.read_excel(uploaded)
        except Exception as e:
            st.error(f"엑셀을 읽는 중 오류가 발생했어요: {e}")
            filter_df = None

        if filter_df is not None:
            filter_df = rules.normalize_columns(filter_df)
            missing = rules.check_columns(filter_df)
            if missing:
                st.error(f"엑셀에 다음 컬럼이 없어서 필터링할 수 없어요: {missing}")
            else:
                filtered = rules.filter_candidates(
                    filter_df,
                    min_search=min_search,
                    max_search=max_search,
                    min_overseas_ratio=min_ratio,
                    min_overseas_review_avg=min_review,
                    exclude_brand=exclude_brand,
                )
                st.session_state["filtered_candidates"] = filtered
                st.success(f"필터링 결과: {len(filtered):,}개 후보")
                display_cols = [
                    c
                    for c in ["키워드", "카테고리", "브랜드키워드", "최근1개월검색량", "계절성", "쿠팡해외배송비율", "쿠팡해외배송평균리뷰수"]
                    if c in filtered.columns
                ]
                st.dataframe(filtered[display_cols], use_container_width=True)
                csv = filtered.to_csv(index=False).encode("utf-8-sig")
                st.download_button("필터링 결과 CSV 다운로드", data=csv, file_name="필터링_후보.csv", mime="text/csv")

    filtered_candidates = st.session_state.get("filtered_candidates")
    if filtered_candidates is not None and len(filtered_candidates) > 0:
        st.markdown("**AI 2차 추천**")
        top_n = st.slider("추천받을 개수", min_value=3, max_value=30, value=10)
        max_candidates = st.slider("AI에게 보여줄 후보 수", 10, 300, 100)
        if st.button("AI 추천 받기"):
            anthropic_key = get_key("anthropic_api_key")
            with st.spinner("AI가 후보를 분석하는 중이에요..."):
                result, error = ai.recommend_categories(anthropic_key, filtered_candidates, top_n=top_n, max_candidates=max_candidates)
            if error:
                st.error(error)
            elif not result:
                st.error("AI 응답을 받지 못했어요.")
            else:
                st.markdown(result)

st.markdown("---")
st.markdown("## 🔍 검색 → 수집 → 카테고리 매칭")

col1, col2, col3, col4 = st.columns(4)
with col1:
    keyword_input = st.text_input(
        "검색 키워드 (한국어 또는 중국어)",
        help="한국어로 넣으면 자동 번역해서 검색해요. 중국어로 넣으면 그대로 검색하고, 카테고리 매칭용으로 한국어로 역번역해요.",
    )
with col2:
    min_price = st.number_input("최저가 (위안)", min_value=0.0, value=0.0, step=1.0)
with col3:
    max_price = st.number_input("최고가 (위안)", min_value=0.0, value=300.0, step=1.0)
with col4:
    max_items = st.number_input("최대 수집 개수 (최소 10)", min_value=10, max_value=500, value=50, step=10)

tmall_only = st.checkbox("티몰(정품 브랜드관)만 검색", value=False)

if st.button("검색·수집 실행", type="primary"):
    anthropic_key = get_key("anthropic_api_key")
    apify_token = get_key("apify_api_token")

    if translate.contains_hangul(keyword_input):
        with st.spinner("한국어 키워드를 중국어로 번역하는 중이에요..."):
            chinese_keyword, t_error = translate.translate_ko_to_zh(keyword_input, anthropic_key)
        korean_keyword = keyword_input
        if not t_error:
            st.info(f"번역된 검색어: **{chinese_keyword}**")
    else:
        chinese_keyword = keyword_input
        with st.spinner("카테고리 매칭용으로 한국어를 추정하는 중이에요..."):
            korean_keyword, t_error = translate.translate_zh_to_ko(keyword_input, anthropic_key)
        if not t_error:
            st.info(f"카테고리 매칭용 한국어: **{korean_keyword}**")

    if t_error:
        st.error(t_error)
    else:

        with st.spinner("Apify에서 타오바오를 검색하는 중이에요..."):
            items, error = apify_scraper.search_products(
                apify_token,
                chinese_keyword,
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

            if len(df) == 0:
                st.session_state.pop("scraped_df", None)
                st.error(
                    f"타오바오 검색은 {before_count}개 나왔는데, **전부 이전에 이미 처리한(아카이브에 있는) 상품**이라 "
                    f"중복 제거하고 나니 신규 상품이 0개예요. 링크가 안 뽑힌 게 아니라 전부 중복이었던 거예요. "
                    "가격범위를 넓히거나 다른 키워드를 써보시거나, 맨 아래 '📦 아카이브 관리'에서 초기화해보세요."
                )
            else:
                st.session_state["scraped_df"] = df
                st.session_state["scraped_keyword"] = chinese_keyword
                st.session_state["scraped_korean_keyword"] = korean_keyword

                if dup_count > 0:
                    st.info(f"이전에 이미 처리한 상품 {dup_count}개는 자동으로 제외했어요.")
                st.success(f"{len(df)}개 상품 수집 완료! (신규 상품 기준)")

                with st.spinner("쿠팡·스스 카테고리 코드 자동매칭 중..."):
                    results = _auto_match_categories(korean_keyword, anthropic_key)
                for system, (code, info, is_estimate) in results.items():
                    if code:
                        label = "추정값" if is_estimate else "자동매칭"
                        st.info(f"[{system} {label}] {code} → {info}")
                    else:
                        st.warning(f"[{system} 카테고리 자동매칭 실패] {info} (아래에서 직접 입력하면 돼요)")

if "scraped_df" in st.session_state:
    st.markdown("---")
    st.markdown("## ⚖️ 무게 확인 및 배송비(추가마진) 계산")
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
    st.markdown("---")
    st.markdown("## 📤 최종 확인 및 픽투셀 양식 다운로드")
    priced_df = st.session_state["priced_df"]
    st.dataframe(priced_df, use_container_width=True)

    exclude_risky = st.checkbox("위험 상품은 제외하고 내보내기", value=True)

    export_df = priced_df[priced_df["위험여부"] == "안전"] if exclude_risky else priced_df
    st.write(f"내보낼 상품 수: {len(export_df)}개 (픽투셀 파일 1개당 최대 500개)")

    st.markdown("#### 카테고리 코드 (검색할 때 자동으로 매칭됨)")
    st.caption("틀렸으면 직접 고치면 돼요 (픽투셀은 둘 다 있으면 쿠팡 기준으로 매칭).")

    c1, c2 = st.columns(2)
    with c1:
        category_code_coupang = st.text_input("쿠팡 카테고리 코드", value=st.session_state.get("matched_category_쿠팡", ""))
    with c2:
        category_code_ss = st.text_input("스스 카테고리 코드", value=st.session_state.get("matched_category_스스", ""))

    if st.button("카테고리 코드 다시 매칭"):
        korean_kw = st.session_state.get("scraped_korean_keyword", "")
        if not korean_kw:
            st.warning("한국어 키워드가 없어요.")
        else:
            anthropic_key = get_key("anthropic_api_key")
            with st.spinner("다시 매칭하는 중..."):
                results = _auto_match_categories(korean_kw, anthropic_key)
            for system, (code, info, is_estimate) in results.items():
                if code:
                    label = "추정값" if is_estimate else "매칭"
                    st.success(f"[{system} {label}] {code} → {info}")
                else:
                    st.error(f"[{system}] {info}")
            st.rerun()

    if st.button("픽투셀 양식 엑셀 만들기", type="primary"):
        if len(export_df) == 0:
            st.warning("내보낼 상품이 없어요.")
        else:
            export_rows = [
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
                export_to_pick2sell_template(export_rows, tmp_path)
                archive.add_to_archive(export_rows, keyword=st.session_state.get("scraped_keyword"))
                with open(tmp_path, "rb") as f:
                    st.download_button(
                        "픽투셀 업로드용 엑셀 다운로드",
                        data=f.read(),
                        file_name="픽투셀_업로드용.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                st.success(f"이 파일을 픽투셀 '엑셀로 일괄등록' 화면에 그대로 올리면 돼요. ({len(export_rows)}개 아카이브에 기록됨)")
            except Exception as e:
                st.error(f"엑셀 생성 실패: {e}")

st.markdown("---")
with st.expander("🚫 개별 상품명 리스크 체크 (선택)"):
    text = st.text_input("상품명 또는 카테고리 입력", key="risk_check_text")
    if st.button("체크하기"):
        reasons = rules.check_risk(text)
        if reasons:
            st.error("위험 항목 발견:")
            for r in reasons:
                st.write(f"- {r}")
        else:
            st.success("블랙리스트/통관배제 키워드가 발견되지 않았어요. (실제 통관 여부는 별도 확인 필요)")

with st.expander("📦 아카이브 관리"):
    archived_count = len(archive.get_archived_urls())
    st.write(f"지금까지 픽투셀로 내보낸 상품: **{archived_count:,}개** (다음 수집 때 자동으로 중복 제외돼요)")
    if st.button("아카이브 초기화 (중복제외 기록 삭제)"):
        archive.clear_archive()
        st.success("아카이브를 초기화했어요.")
        st.rerun()
