import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

import pandas as pd
import streamlit as st

from lib import ai, apify_scraper, archive, category_code, margin, rules
from lib.pick2sell_export import export_to_pick2sell_template
from lib.shipping import PACKAGING_TYPES
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="자동수집 통합", page_icon="🕷️", layout="wide")
render_api_key_sidebar()

st.title("🕷️ 타오바오 자동수집 → 마진계산 → 픽투셀 양식 출력")
st.caption("키워드 하나로 검색부터 픽투셀 업로드용 엑셀까지 한번에 처리해요. (Apify API 토큰 필요)")

st.markdown("### 1단계. 타오바오 검색·수집")

col1, col2, col3, col4 = st.columns(4)
with col1:
    keyword = st.text_input("검색 키워드 (중국어)", help="③ 키워드 번역 페이지에서 번역한 결과를 넣으세요")
with col2:
    min_price = st.number_input("최저가 (위안)", min_value=0.0, value=0.0, step=1.0)
with col3:
    max_price = st.number_input("최고가 (위안)", min_value=0.0, value=300.0, step=1.0)
with col4:
    max_items = st.number_input("최대 수집 개수 (최소 10)", min_value=10, max_value=500, value=50, step=10)

korean_keyword = st.text_input(
    "한국어 키워드/카테고리 (선택, 쿠팡 카테고리 코드 자동매칭용)",
    help="예: '캠핑 랜턴'. 비워두면 카테고리 코드는 자동매칭 안 하고 빈칸으로 나가요.",
)

tmall_only = st.checkbox("티몰(정품 브랜드관)만 검색", value=False)

if st.button("① 타오바오 검색·수집 실행", type="primary"):
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
        st.session_state["scraped_korean_keyword"] = korean_keyword
        st.session_state.pop("matched_category_code", None)

        if dup_count > 0:
            st.info(f"이전에 이미 처리한 상품 {dup_count}개는 자동으로 제외했어요.")
        st.success(f"{len(df)}개 상품 수집 완료! (신규 상품 기준)")

if "scraped_df" in st.session_state:
    st.markdown("### 2단계. 무게 확인 후 마진 계산")
    st.caption("타오바오 검색결과엔 무게 정보가 없어서, 예상무게를 직접 입력/수정해야 해요. (표를 직접 클릭해서 수정 가능)")

    edited_df = st.data_editor(
        st.session_state["scraped_df"],
        use_container_width=True,
        num_rows="fixed",
        key="scraped_editor",
    )
    st.session_state["scraped_df"] = edited_df

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        exchange_rate = st.number_input("환율 (1위안=?원)", min_value=0.0, value=195.0, step=0.1)
    with c2:
        margin_rate = st.number_input("마진율", min_value=0.0, value=margin.DEFAULT_MARGIN_RATE, step=0.05, format="%.2f")
    with c3:
        extra_margin = st.number_input("추가마진(정액,원)", min_value=0, value=margin.DEFAULT_EXTRA_MARGIN, step=1000)
    with c4:
        packaging_type = st.selectbox("포장방식", list(PACKAGING_TYPES.keys()))
    shipping_method = st.selectbox("배송방식", ["해운", "항공"])

    if st.button("② 마진계산 + 리스크체크 실행", type="primary"):
        result_rows = []
        for _, row in edited_df.iterrows():
            if pd.isna(row["원가위안"]):
                continue
            calc = margin.calculate_final_price(
                cost_cny=row["원가위안"],
                exchange_rate=exchange_rate,
                weight_kg=row["예상무게(kg)"],
                shipping_method=shipping_method,
                packaging_type=packaging_type,
                margin_rate=margin_rate,
                extra_margin=extra_margin,
            )
            reasons = rules.check_risk(row["상품명"] or "")
            result_rows.append(
                {
                    "상품명": row["상품명"],
                    "URL": row["URL"],
                    "원가위안": row["원가위안"],
                    "예상무게(kg)": row["예상무게(kg)"],
                    "최종판매가": calc["최종판매가"],
                    "위험여부": "위험" if reasons else "안전",
                    "위험사유": " / ".join(reasons),
                }
            )
        st.session_state["priced_df"] = pd.DataFrame(result_rows)

if "priced_df" in st.session_state:
    st.markdown("### 3단계. 최종 확인 후 픽투셀 양식 다운로드")
    priced_df = st.session_state["priced_df"]
    st.dataframe(priced_df, use_container_width=True)

    exclude_risky = st.checkbox("위험 상품은 제외하고 내보내기", value=True)

    export_df = priced_df[priced_df["위험여부"] == "안전"] if exclude_risky else priced_df
    st.write(f"내보낼 상품 수: {len(export_df)}개 (픽투셀 파일 1개당 최대 500개)")

    st.markdown("#### 카테고리 코드 자동매칭 (선택)")
    st.caption("검색에 쓴 키워드/카테고리로 쿠팡·스스 카테고리 코드를 찾아서 전체 상품에 똑같이 적용해요. 둘 다 채워도 되고, 하나만 써도 돼요(픽투셀은 둘 다 있으면 쿠팡 기준으로 매칭).")

    category_keyword = st.text_input(
        "카테고리 매칭용 한국어 키워드",
        value=st.session_state.get("scraped_korean_keyword", ""),
    )

    if st.button("카테고리 코드 자동매칭 실행"):
        anthropic_key = get_key("anthropic_api_key")
        for system in ["쿠팡", "스스"]:
            candidates = category_code.find_candidates(category_keyword, system=system)
            if not candidates:
                st.warning(f"[{system}] 후보 카테고리를 못 찾았어요. 키워드를 바꿔보세요.")
                continue
            code, error = ai.match_category_code(anthropic_key, category_keyword, candidates)
            if error:
                st.error(f"[{system}] {error}")
            else:
                path = dict(candidates)[code]
                st.session_state[f"matched_category_{system}"] = code
                st.success(f"[{system}] {code} → {path}")

    c1, c2 = st.columns(2)
    with c1:
        category_code_coupang = st.text_input("쿠팡 카테고리 코드 (직접 수정 가능)", value=st.session_state.get("matched_category_쿠팡", ""))
    with c2:
        category_code_ss = st.text_input("스스 카테고리 코드 (직접 수정 가능)", value=st.session_state.get("matched_category_스스", ""))

    if st.button("③ 픽투셀 양식 엑셀 만들기", type="primary"):
        if len(export_df) == 0:
            st.warning("내보낼 상품이 없어요.")
        else:
            rows = [
                {
                    "url": r["URL"],
                    "title": r["상품명"],
                    "category_code_coupang": category_code_coupang,
                    "category_code_ss": category_code_ss,
                    "target_price": r["최종판매가"],
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
