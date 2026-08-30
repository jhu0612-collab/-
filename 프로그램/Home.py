import os
import tempfile

import pandas as pd
import streamlit as st

from lib import ai, apify_scraper, archive, batch_pipeline, category_code, naver_datalab, naver_searchad, pricing, rules, translate
from lib import shipping as shipping_calc
from lib.pick2sell_export import export_to_pick2sell_template
from lib.shipping import PACKAGING_TYPES
from lib.state import get_key, render_api_key_sidebar

st.set_page_config(page_title="해구대 소싱 자동화", page_icon="📦", layout="wide")
render_api_key_sidebar()

st.title("📦 해구대 소싱 자동화 도구")
st.caption("키워드 하나로 번역 → 검색·수집 → 무게·배송비 계산 → 카테고리 매칭 → 픽투셀 업로드용 엑셀까지 한 화면에서 처리해요.")


def _fetch_related_keywords(korean_keyword):
    """검색광고 API 키가 설정돼 있으면 연관키워드(실제 검색량 높은 순)를 가져온다.

    키가 없거나 조회에 실패하면 조용히 None을 반환한다 - 이 기능은 선택 사항이라
    SEO 제목 생성 자체를 막으면 안 된다."""
    api_key = get_key("naver_searchad_api_key")
    secret_key = get_key("naver_searchad_secret_key")
    customer_id = get_key("naver_searchad_customer_id")
    if not (api_key and secret_key and customer_id):
        return None
    items, error = naver_searchad.get_related_keywords(api_key, secret_key, customer_id, korean_keyword)
    if error or not items:
        return None
    return naver_searchad.top_keyword_strings(items, exclude=korean_keyword)


def _auto_match_categories(korean_keyword, anthropic_key):
    """반환값: {system: (code, 설명, 추정여부)}.

    부분단어로 후보를 못 찾은 경우뿐 아니라, 후보는 있는데 AI가 그중에 적합한 걸
    하나도 못 골랐을 때(예: "없음" 응답)도 그냥 공백으로 두지 않고, 대분류부터
    추정하는 guess_category_fallback으로 한 번 더 시도해서 근사치라도 채운다."""
    results = {}
    for system in ["쿠팡", "스스"]:
        candidates = category_code.find_candidates(korean_keyword, system=system)
        code, info, is_estimate = None, None, False
        if candidates:
            code, error = ai.match_category_code(anthropic_key, korean_keyword, candidates)
            info = dict(candidates)[code] if code else error

        if not code:
            fallback_code, fallback_info = ai.guess_category_fallback(anthropic_key, korean_keyword, system)
            if fallback_code:
                code, info, is_estimate = fallback_code, fallback_info, True
            elif fallback_info:
                info = fallback_info

        if code:
            st.session_state[f"matched_category_{system}"] = code
        results[system] = (code, info, is_estimate)
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

    def _apply_seller_life_filter(raw_df):
        raw_df = rules.normalize_columns(raw_df)
        missing = rules.check_columns(raw_df)
        if missing:
            st.error(f"엑셀에 다음 컬럼이 없어서 필터링할 수 없어요: {missing}")
            return None
        return rules.filter_candidates(
            raw_df,
            min_search=min_search,
            max_search=max_search,
            min_overseas_ratio=min_ratio,
            min_overseas_review_avg=min_review,
            exclude_brand=exclude_brand,
        )

    def _show_filtered_result(filtered):
        st.session_state["filtered_candidates"] = filtered
        st.success(f"필터링 결과: {len(filtered):,}개 후보")
        display_cols = [
            c
            for c in ["키워드", "카테고리", "브랜드키워드", "최근1개월검색량", "계절성", "쿠팡해외배송비율", "쿠팡해외배송평균리뷰수"]
            if c in filtered.columns
        ]
        st.dataframe(filtered[display_cols], width='stretch')
        csv = filtered.to_csv(index=False).encode("utf-8-sig")
        st.download_button("필터링 결과 CSV 다운로드", data=csv, file_name="필터링_후보.csv", mime="text/csv")

    source_tab1, source_tab2 = st.tabs(["엑셀 1개 업로드", "📁 폴더에서 여러 개 한번에"])
    with source_tab1:
        uploaded = st.file_uploader("셀러라이프 엑셀 업로드 (.xlsx)", type=["xlsx"])
        if uploaded is not None:
            try:
                filter_df = pd.read_excel(uploaded)
            except Exception as e:
                st.error(f"엑셀을 읽는 중 오류가 발생했어요: {e}")
                filter_df = None
            if filter_df is not None:
                filtered = _apply_seller_life_filter(filter_df)
                if filtered is not None:
                    _show_filtered_result(filtered)

    with source_tab2:
        st.caption(
            "며칠/몇 주마다 셀러라이프에서 새로 뽑은 엑셀들을 이 폴더에 계속 갈아끼워두면, "
            "매번 업로드 안 하고 폴더에 있는 파일 전부를 합쳐서 한 번에 필터링해요."
        )
        seller_life_dir = st.text_input(
            "셀러라이프 엑셀 모음 폴더 경로", value=os.path.join("data", "셀러라이프_모음")
        )
        if st.button("📁 폴더에서 불러와서 필터링"):
            if not os.path.isdir(seller_life_dir):
                st.error(f"폴더를 찾을 수 없어요: {seller_life_dir} (먼저 폴더를 만들고 엑셀을 넣어주세요)")
            else:
                excel_files = [f for f in os.listdir(seller_life_dir) if f.lower().endswith((".xlsx", ".xls"))]
                if not excel_files:
                    st.warning(f"'{seller_life_dir}' 폴더에 엑셀 파일이 없어요.")
                else:
                    dfs = []
                    for fname in excel_files:
                        try:
                            dfs.append(pd.read_excel(os.path.join(seller_life_dir, fname)))
                        except Exception as e:
                            st.warning(f"'{fname}' 읽기 실패, 건너뜀: {e}")
                    if not dfs:
                        st.error("읽을 수 있는 엑셀이 하나도 없었어요.")
                    else:
                        combined_raw = pd.concat(dfs, ignore_index=True)
                        st.info(f"엑셀 {len(dfs)}개, 총 {len(combined_raw):,}행을 합쳤어요.")
                        filtered = _apply_seller_life_filter(combined_raw)
                        if filtered is not None:
                            _show_filtered_result(filtered)

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

        st.markdown("**🔥 네이버 데이터랩으로 최근 트렌드 재정렬 (선택)**")
        st.caption(
            "주의: 데이터랩은 새 키워드를 발굴해주는 게 아니라, 이미 있는 후보들 사이의 상대적 "
            "검색 트렌드만 비교해줘요. 네이버 쇼핑인사이트 '분야 코드'를 알아야 조회할 수 있어요 "
            "(developers.naver.com 데이터랩 문서에서 분야별 코드 확인 가능)."
        )
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            datalab_category_code = st.text_input("네이버 데이터랩 분야 코드", value="")
        with dl_col2:
            datalab_top_n = st.slider("트렌드 비교할 후보 개수", min_value=5, max_value=30, value=10)
        if st.button("🔥 트렌드로 재정렬"):
            naver_client_id = get_key("naver_client_id")
            naver_client_secret = get_key("naver_client_secret")
            if not datalab_category_code:
                st.warning("네이버 데이터랩 분야 코드를 입력해주세요.")
            elif "키워드" not in filtered_candidates.columns:
                st.error("후보 목록에 '키워드' 컬럼이 없어요.")
            else:
                candidate_keywords = filtered_candidates["키워드"].dropna().astype(str).unique().tolist()[:datalab_top_n]
                with st.spinner("네이버 데이터랩에서 트렌드를 조회하는 중..."):
                    ranked, dl_error = naver_datalab.rank_keywords_by_recent_trend(
                        naver_client_id, naver_client_secret, datalab_category_code, candidate_keywords
                    )
                if dl_error:
                    st.warning(f"일부/전체 실패: {dl_error}")
                if ranked:
                    st.dataframe(
                        pd.DataFrame(ranked, columns=["키워드", "최근트렌드지수(참고용)"]), width='stretch'
                    )

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
exclude_bait_price = st.checkbox(
    "미끼가격 의심 상품은 수집 단계에서 아예 제외",
    value=False,
    help=(
        "끄면(기본값) '확인필요'로 표시만 하고 목록엔 남겨둬요. 켜면 아예 목록에서 빼버려서 "
        "수집 개수가 줄어들 수 있어요 (이미 스크랩 비용은 똑같이 나가요, 결과에서 제외만 되는 거예요)."
    ),
)
enrich_with_details = st.checkbox(
    "🧪 상세정보(enrichWithDetails) 켜서 정확도 강화",
    value=False,
    help=(
        "기본은 꺼져있어요(건당 비용이 거의 2배로 늘어나요). 켜면 상품마다 상세페이지 속성(attributes)까지 "
        "가져와서: ① 제목엔 안 나오는 주문제작 상품도 자동으로 걸러내고, ② 실측 무게 속성이 있으면 "
        "AI 추측 대신 그 값을 그대로 써서 무게추산이 더 정확해지고, ③ 110V 전용(한국에서 못 쓰는) 상품을 "
        "자동으로 제외하고, ④ SEO 제목 생성 때 재질/기능 같은 실제 스펙을 참고해요. 다만 배송예정(예: "
        "주문제작 확인 후 며칠 이내 발송) 문구 자체는 이 액터가 아예 안 주는 정보라 여전히 못 잡아요."
    ),
)

if st.button("검색·수집 실행", type="primary"):
    anthropic_key = get_key("anthropic_api_key")
    apify_token = get_key("apify_api_token")

    if translate.contains_hangul(keyword_input):
        with st.spinner("한국어 키워드를 중국어로 번역하는 중이에요..."):
            chinese_keyword, t_error = translate.translate_ko_to_zh(keyword_input, anthropic_key)
        # SEO 상품명 메인키워드는 항상 띄어쓰기 없이 붙여쓰기로 통일한다 (직접 입력한 경우도 동일).
        korean_keyword = keyword_input.replace(" ", "")
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
                enrich_with_details=enrich_with_details,
            )

        if error:
            st.error(error)
        elif not items:
            st.warning("검색 결과가 없어요. 키워드나 가격범위를 확인해보세요.")
        else:
            actor_error = apify_scraper.find_actor_error(items)
            if actor_error:
                st.error(
                    f"Apify 액터(수집기)에서 에러를 반환했어요: {actor_error}\n\n"
                    "'무료 체험 횟수 소진(free tier exhausted)' 메시지라면, 코드 문제가 아니라 "
                    "이 액터 자체의 사용 한도예요. https://apify.com/pricing 에서 해당 액터를 "
                    "유료로 구독(Rent)하거나 대여해야 계속 쓸 수 있어요."
                )
                st.stop()

            rows = apify_scraper.to_rows(items)
            if not rows:
                st.warning(
                    f"Apify가 {len(items)}건을 반환했지만 실제 상품(URL/가격이 있는)이 하나도 없었어요. "
                    "타오바오 사이트에는 결과가 있어도, Apify 수집기 쪽이 캡차/차단 등으로 막혔을 가능성이 커요. "
                    "잠시 후 다시 시도하거나 키워드를 살짝 바꿔서 시도해보세요."
                )
                with st.expander("🔧 Apify가 실제로 반환한 원본 데이터 보기 (디버그용)"):
                    st.json(items)
                st.stop()

            with st.expander("🔧 원본 데이터 확인 (문제 리포트용)"):
                st.caption(
                    "특정 상품이 필터링에서 이상하게 빠지거나 안 빠지는 것 같으면, 여기서 펼쳐서 "
                    "해당 상품 부분을 찾아 통째로 복사해 전달해주세요."
                )
                st.json(items)

            df = pd.DataFrame(rows)

            before_service_count = len(df)
            df = df[~df["상품명"].apply(rules.is_service_listing)].reset_index(drop=True)
            service_count = before_service_count - len(df)

            before_custom_order_count = len(df)
            custom_order_mask = df["상품명"].apply(rules.is_custom_order_listing)
            if "_주문제작속성감지" in df.columns:
                custom_order_mask = custom_order_mask | df["_주문제작속성감지"]
            df = df[~custom_order_mask].reset_index(drop=True)
            custom_order_count = before_custom_order_count - len(df)
            df = df.drop(columns=["_주문제작속성감지"], errors="ignore")

            before_110v_count = len(df)
            if "_110V전용" in df.columns:
                df = df[~df["_110V전용"]].reset_index(drop=True)
            voltage_excluded_count = before_110v_count - len(df)
            df = df.drop(columns=["_110V전용"], errors="ignore")

            bait_excluded_count = 0
            if exclude_bait_price and "가격편차배수" in df.columns:
                before_bait_count = len(df)
                bait_mask = df.apply(
                    lambda r: apify_scraper.is_bait_price_suspected(r["최저가위안"], r["가격편차배수"]), axis=1
                )
                df = df[~bait_mask].reset_index(drop=True)
                bait_excluded_count = before_bait_count - len(df)

            archived_urls = archive.get_archived_urls()
            before_count = len(df)
            df = df[~df["URL"].isin(archived_urls)].reset_index(drop=True)
            dup_count = before_count - len(df)

            irrelevant_count = 0
            relevance_check_failed = False
            if len(df) > 0:
                with st.spinner("AI가 검색어와 실제로 맞는 상품인지 확인하는 중..."):
                    rel_attribute_contexts = df["참고속성"].tolist() if "참고속성" in df.columns else None
                    relevance, relevance_error = ai.check_relevance(
                        anthropic_key, df["상품명"].tolist(), korean_keyword, attribute_contexts=rel_attribute_contexts
                    )
                if relevance_error:
                    relevance_check_failed = True
                else:
                    before_relevance_count = len(df)
                    df = df[pd.Series(relevance, index=df.index)].reset_index(drop=True)
                    irrelevant_count = before_relevance_count - len(df)

            df["예상무게(kg)"] = 1.0
            df.insert(0, "선택", False)

            if len(df) == 0:
                st.session_state.pop("scraped_df", None)
                st.error(
                    f"타오바오 검색은 {before_service_count}개 나왔는데, "
                    f"출장설치/서비스성 상품 {service_count}개, 주문제작 상품 {custom_order_count}개, "
                    f"110V 전용 상품 {voltage_excluded_count}개, "
                    f"미끼가격 의심 {bait_excluded_count}개, "
                    f"검색어와 무관한 상품 {irrelevant_count}개, "
                    f"아카이브 중복 {dup_count}개를 제외하고 나니 신규 상품이 0개예요. "
                    "가격범위를 넓히거나 다른 키워드를 써보시거나, 맨 아래 '📦 아카이브 관리'에서 초기화해보세요."
                )
            else:
                st.session_state["scraped_df"] = df
                st.session_state["scraped_keyword"] = chinese_keyword
                st.session_state["scraped_korean_keyword"] = korean_keyword

                if service_count > 0:
                    st.info(f"출장설치/조립 등 서비스성 상품 {service_count}개는 해외배송이 불가능해서 자동으로 제외했어요.")
                if custom_order_count > 0:
                    st.info(f"주문제작(맞춤 사이즈/사양) 상품 {custom_order_count}개는 표준 발주가 불가능해서 자동으로 제외했어요.")
                if voltage_excluded_count > 0:
                    st.info(f"110V 전용(한국에서 그대로 못 씀) 상품 {voltage_excluded_count}개를 자동으로 제외했어요.")
                if bait_excluded_count > 0:
                    st.info(f"미끼가격 의심 상품 {bait_excluded_count}개를 수집 단계에서 제외했어요.")
                if relevance_check_failed:
                    st.warning(f"검색어 관련성 확인({relevance_error}) 실패해서 이 단계는 건너뛰었어요.")
                elif irrelevant_count > 0:
                    st.info(f"검색어(\"{korean_keyword}\")와 실제로 무관해 보이는 상품 {irrelevant_count}개를 AI가 걸러냈어요.")
                if dup_count > 0:
                    st.info(f"이전에 이미 처리한 상품 {dup_count}개는 자동으로 제외했어요.")
                st.success(f"{len(df)}개 상품 수집 완료! (신규 상품 기준)")

                if "가격편차배수" in df.columns:
                    bait_mask = df.apply(
                        lambda r: apify_scraper.is_bait_price_suspected(r["최저가위안"], r["가격편차배수"]), axis=1
                    )
                    bait_count = bait_mask.sum()
                    if bait_count > 0:
                        st.warning(
                            f"미끼가격 의심 상품 {bait_count}개가 있어요 (최저가가 비정상적으로 싸면서 편차도 크거나, "
                            "편차가 8배 이상으로 극단적인 경우). 실제로 원하는 옵션이 픽투셀에 정상 등록되는지 "
                            "직접 확인해보세요. 아래 표의 '최저가위안'/'최고가위안' 컬럼에서 확인 가능해요."
                        )

                with st.spinner("쿠팡·스스 카테고리 코드 자동매칭 중..."):
                    results = _auto_match_categories(korean_keyword, anthropic_key)
                for system, (code, info, is_estimate) in results.items():
                    if code:
                        label = "추정값" if is_estimate else "자동매칭"
                        st.info(f"[{system} {label}] {code} → {info}")
                    else:
                        st.warning(f"[{system} 카테고리 자동매칭 실패] {info} (아래에서 직접 입력하면 돼요)")

                related_keywords = _fetch_related_keywords(korean_keyword)
                if related_keywords:
                    st.caption(f"🔎 검색광고 실제 검색량 반영: {', '.join(related_keywords)}")
                with st.spinner("AI가 상품명을 한국어 SEO 제목으로 변환하는 중..."):
                    attribute_contexts = df["참고속성"].tolist() if "참고속성" in df.columns else None
                    seo_titles, seo_error = ai.generate_seo_titles(
                        anthropic_key,
                        df["상품명"].tolist(),
                        korean_keyword,
                        attribute_contexts=attribute_contexts,
                        related_keywords=related_keywords,
                    )
                if seo_titles is None:
                    df["한국어상품명(SEO)"] = ""
                    df["제목글자수"] = 0
                    st.session_state["scraped_df"] = df
                    st.warning(
                        f"한국어 상품명 자동생성 실패: {seo_error} "
                        "(중국어 원본은 절대 안 쓰고 빈 칸으로 둬요. 아래 '🈶 한국어 상품명 다시 생성' 버튼으로 재시도하거나, "
                        "표에서 직접 입력해도 돼요.)"
                    )
                else:
                    if seo_error:
                        # 일부만 실패한 경우 - 성공한 부분은 살리고, 실패한 부분(빈 칸)만 안내한다.
                        st.warning(seo_error)
                    df["한국어상품명(SEO)"] = seo_titles
                    df["제목글자수"] = [len(t) for t in seo_titles]
                    st.session_state["scraped_df"] = df

st.markdown("---")
st.markdown("## 🗂 여러 키워드 일괄 처리")
st.caption(
    "위 단일 키워드 흐름을 여러 키워드에 대해 순서대로 자동으로 돌리고, 결과를 하나로 합쳐요. "
    "키워드 개수만큼 Apify/AI 비용이 그대로 늘어나니(예: 10개 키워드면 대략 10배), "
    "한 번에 너무 많이 돌리지 않는 걸 추천해요."
)
batch_keywords_text = st.text_area(
    "키워드 목록 (한 줄에 하나씩, 한국어 또는 중국어)",
    height=120,
    help="예시:\n철근결속기\n낚시구명조끼\n접이식킥보드",
)
batch_col1, batch_col2, batch_col3, batch_col4 = st.columns(4)
with batch_col1:
    batch_max_items = st.number_input("키워드당 최대 수집 개수", min_value=10, max_value=200, value=20, step=10)
with batch_col2:
    batch_max_keywords = st.number_input("한 번에 처리할 최대 키워드 수(안전장치)", min_value=1, max_value=30, value=10)
with batch_col3:
    batch_exclude_bait = st.checkbox("미끼가격 의심 상품 제외", value=exclude_bait_price, key="batch_exclude_bait")
with batch_col4:
    batch_enrich_with_details = st.checkbox(
        "🧪 상세정보(enrichWithDetails) 강화", value=enrich_with_details, key="batch_enrich_with_details"
    )

if st.button("🗂 일괄 검색·수집 실행", type="primary"):
    anthropic_key = get_key("anthropic_api_key")
    apify_token = get_key("apify_api_token")
    keywords = [k.strip() for k in batch_keywords_text.splitlines() if k.strip()]
    if not keywords:
        st.warning("키워드를 한 줄에 하나씩 입력해주세요.")
    else:
        if len(keywords) > batch_max_keywords:
            st.info(f"입력한 {len(keywords)}개 중 앞의 {int(batch_max_keywords)}개만 처리해요 (안전장치 설정값).")
        keywords = keywords[: int(batch_max_keywords)]

        archived_urls = archive.get_archived_urls()
        seen_urls_this_batch = set()
        all_dfs = []
        batch_log = []
        progress = st.progress(0.0)
        for i, kw in enumerate(keywords):
            progress.progress(i / len(keywords), text=f"({i + 1}/{len(keywords)}) '{kw}' 처리 중...")
            result = batch_pipeline.run_single_keyword(
                kw,
                min_price=0,
                max_price=0,
                max_items=batch_max_items,
                tmall_only=False,
                exclude_bait_price=batch_exclude_bait,
                enrich_with_details=batch_enrich_with_details,
                anthropic_key=anthropic_key,
                apify_token=apify_token,
                archived_urls=archived_urls | seen_urls_this_batch,
                naver_searchad_api_key=get_key("naver_searchad_api_key"),
                naver_searchad_secret_key=get_key("naver_searchad_secret_key"),
                naver_searchad_customer_id=get_key("naver_searchad_customer_id"),
            )
            if result["error"]:
                batch_log.append(f"❌ **{kw}**: {result['error']}")
            else:
                all_dfs.append(result["df"])
                seen_urls_this_batch.update(result["df"]["URL"].tolist())
                batch_log.append(f"✅ **{kw}**: {len(result['df'])}개 수집 ({', '.join(result['log'])})")
        progress.progress(1.0, text="완료!")

        st.markdown("**처리 결과**")
        for line in batch_log:
            st.write(line)

        if all_dfs:
            combined = pd.concat(all_dfs, ignore_index=True)
            st.session_state["scraped_df"] = combined
            st.session_state["scraped_keyword"] = "(여러 키워드 일괄)"
            st.session_state["scraped_korean_keyword"] = "(여러 키워드 일괄)"
            st.success(f"{len(all_dfs)}개 키워드에서 총 {len(combined)}개 상품을 합쳐서 아래 무게/배송비 계산 단계로 넘겼어요.")
            st.rerun()
        else:
            st.error("모든 키워드에서 결과를 못 얻었어요. 위 로그를 확인해보세요.")

if "scraped_df" in st.session_state:
    st.markdown("---")
    st.markdown("## ⚖️ 무게 확인 및 배송비(추가마진) 계산")
    st.caption(
        "타오바오 검색결과엔 무게 정보가 없어서, 예상무게를 직접 입력/수정해야 해요 (대충 추산해서 넣으면 돼요). "
        "원가×마진율 계산은 픽투셀이 자체 설정대로 알아서 하고, 저희는 무게 기준 배송비만 계산해서 '추가마진'에 얹어요."
    )

    weight_col, seo_col = st.columns(2)
    with weight_col:
        if st.button("🤖 AI로 상품별 무게 자동추산", type="primary"):
            anthropic_key = get_key("anthropic_api_key")
            current_df = st.session_state["scraped_df"]

            if "속성무게kg" in current_df.columns:
                has_attr_weight = current_df["속성무게kg"].notna()
            else:
                has_attr_weight = pd.Series([False] * len(current_df))

            titles_to_estimate = current_df.loc[~has_attr_weight, "상품명"].tolist()
            attr_covered = int(has_attr_weight.sum())

            ai_weights, error = (None, None)
            if titles_to_estimate:
                with st.spinner(
                    f"AI가 상품명을 보고 종류별로 무게를 추산하는 중이에요... "
                    f"(속성에서 실측 무게가 확인된 {attr_covered}개는 AI 호출 없이 그대로 써요)"
                ):
                    ai_weights, error = ai.estimate_weights(anthropic_key, titles_to_estimate)

            if error:
                st.error(error)
            else:
                ai_iter = iter(ai_weights or [])
                final_weights = [
                    row["속성무게kg"] if has_attr_weight.iloc[i] else next(ai_iter)
                    for i, (_, row) in enumerate(current_df.iterrows())
                ]
                st.session_state["scraped_df"]["예상무게(kg)"] = [
                    shipping_calc.round_up_to_half_kg(w) for w in final_weights
                ]
                msg = "무게 추산 완료!"
                if attr_covered:
                    msg += f" ({attr_covered}개는 상세속성 실측값, {len(titles_to_estimate)}개는 AI 추정)"
                st.success(f"{msg} 참고용이니 아래 표에서 확인하고 이상하면 직접 고치세요.")
                st.rerun()
    with seo_col:
        if st.button("🈶 한국어 상품명(SEO) 다시 생성"):
            anthropic_key = get_key("anthropic_api_key")
            korean_kw = st.session_state.get("scraped_korean_keyword", "")
            current_df = st.session_state["scraped_df"]
            titles = current_df["상품명"].tolist()
            attribute_contexts = current_df["참고속성"].tolist() if "참고속성" in current_df.columns else None
            related_keywords = _fetch_related_keywords(korean_kw)
            if related_keywords:
                st.caption(f"🔎 검색광고 실제 검색량 반영: {', '.join(related_keywords)}")
            with st.spinner("AI가 한국어 SEO 제목을 생성하는 중이에요..."):
                seo_titles, error = ai.generate_seo_titles(
                    anthropic_key,
                    titles,
                    korean_kw,
                    attribute_contexts=attribute_contexts,
                    related_keywords=related_keywords,
                )
            if seo_titles is None:
                st.error(f"{error} (중국어 원본은 절대 안 쓰고 빈 칸으로 둬요.)")
            else:
                st.session_state["scraped_df"]["한국어상품명(SEO)"] = seo_titles
                st.session_state["scraped_df"]["제목글자수"] = [len(t) for t in seo_titles]
                if error:
                    st.warning(error)
                else:
                    st.success("한국어 상품명 생성 완료! 아래 표에서 확인하세요.")
                st.rerun()

    bulk_col1, bulk_col2 = st.columns([1, 3])
    with bulk_col1:
        bulk_weight = st.number_input("전체 동일 무게로 일괄 적용(kg)", min_value=0.0, value=1.0, step=0.1)
    with bulk_col2:
        st.write("")
        if st.button("⬆ 위 무게를 전체 상품에 한번에 적용"):
            st.session_state["scraped_df"]["예상무게(kg)"] = shipping_calc.round_up_to_half_kg(bulk_weight)
            st.rerun()

    st.caption("전체 상품 무게를 상대적으로 한번에 조정하기 (지금 무게에 더하거나 빼요)")
    adj_col1, adj_col2, adj_col3, adj_col4 = st.columns(4)
    for col, delta, label in [
        (adj_col1, 0.5, "+0.5kg 높이기"),
        (adj_col2, 1.0, "+1kg 높이기"),
        (adj_col3, -0.5, "-0.5kg 낮추기"),
        (adj_col4, -1.0, "-1kg 낮추기"),
    ]:
        with col:
            if st.button(label):
                st.session_state["scraped_df"]["예상무게(kg)"] = st.session_state["scraped_df"]["예상무게(kg)"].apply(
                    lambda w: shipping_calc.round_up_to_half_kg(max(0.1, w + delta))
                )
                st.rerun()

    st.caption(
        "전 상품이 다 비슷한 무게면 일괄적용, 상품마다 다르면 AI 추산 후 표에서 미세조정하세요. "
        "동백 요금이 0.5kg 단위로 끊어 청구돼서, 무게는 항상 0.5kg 단위로 올림해서 표시돼요 (예: 0.8→1.0, 1.1→1.5)."
    )

    st.caption("맨 왼쪽 '선택' 체크박스로 원하는 상품만 골라서 아래 버튼으로 삭제하거나 무게를 조정할 수 있어요.")
    edited_df = st.data_editor(
        st.session_state["scraped_df"],
        width='stretch',
        num_rows="fixed",
        key="scraped_editor",
    )
    st.session_state["scraped_df"] = edited_df

    selected_mask = edited_df["선택"] == True  # noqa: E712 (pandas bool 컬럼 명시적 비교)
    selected_count = int(selected_mask.sum())

    sel_del_col, sel_adj_col1, sel_adj_col2, sel_adj_col3, sel_adj_col4 = st.columns(5)
    with sel_del_col:
        if st.button(f"🗑 선택({selected_count}개) 삭제"):
            if selected_count == 0:
                st.warning("선택된 상품이 없어요.")
            else:
                st.session_state["scraped_df"] = edited_df[~selected_mask].reset_index(drop=True)
                st.rerun()
    for col, delta, label in [
        (sel_adj_col1, 0.5, "+0.5kg"),
        (sel_adj_col2, 1.0, "+1kg"),
        (sel_adj_col3, -0.5, "-0.5kg"),
        (sel_adj_col4, -1.0, "-1kg"),
    ]:
        with col:
            if st.button(f"선택 {label}"):
                if selected_count == 0:
                    st.warning("선택된 상품이 없어요.")
                else:
                    edited_df.loc[selected_mask, "예상무게(kg)"] = edited_df.loc[selected_mask, "예상무게(kg)"].apply(
                        lambda w: shipping_calc.round_up_to_half_kg(max(0.1, w + delta))
                    )
                    st.session_state["scraped_df"] = edited_df
                    st.rerun()

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
            korean_title = row.get("한국어상품명(SEO)") or ""
            # 원본 중국어 제목도 같이 검사한다 - SEO 제목 생성 규칙상 브랜드명은
            # AI가 이미 지우고 나오기 때문에, 원본을 안 보면 브랜드 상품이 안 걸러진다.
            reasons = rules.check_risk(f"{korean_title} {row['상품명'] or ''}")
            price_ratio = row.get("가격편차배수")
            min_price_yuan = row.get("최저가위안")
            if (
                price_ratio is not None
                and not pd.isna(price_ratio)
                and apify_scraper.is_bait_price_suspected(min_price_yuan, price_ratio)
            ):
                reasons.append(
                    (
                        f"가격편차 큼 (최저 ¥{min_price_yuan}~최고 ¥{row.get('최고가위안')}, "
                        f"{price_ratio}배) - 미끼가격 의심, 픽투셀에 원하는 옵션이 정상 등록되는지 직접 확인 필요",
                        True,
                    )
                )
            result_rows.append(
                {
                    "상품명": row["상품명"],
                    "한국어상품명(SEO)": korean_title,
                    "URL": row["URL"],
                    "원가위안": row["원가위안"],
                    "예상무게(kg)": billed_weight,
                    "배송비": shipping["배송비합계"],
                    "추가마진": shipping["배송비합계"] + extra_margin_base,
                    "위험여부": rules.classify_risk(reasons),
                    "위험사유": " / ".join(r for r, _ in reasons),
                    # 여러 키워드 일괄 처리로 수집된 경우 키워드마다 카테고리가 다를 수 있어서
                    # 행별로 들고 다닌다 (단일 키워드 검색 결과엔 이 컬럼 자체가 없음).
                    "쿠팡카테고리코드": row.get("쿠팡카테고리코드", ""),
                    "스스카테고리코드": row.get("스스카테고리코드", ""),
                    "검색키워드": row.get("검색키워드") or st.session_state.get("scraped_korean_keyword", ""),
                }
            )
        st.session_state["priced_df"] = pd.DataFrame(result_rows)

if "priced_df" in st.session_state:
    st.markdown("---")
    st.markdown("## 📤 최종 확인 및 픽투셀 양식 다운로드")
    priced_df = st.session_state["priced_df"]
    st.dataframe(priced_df, width='stretch')

    with st.expander("💰 시장가 비교 + 경쟁력있는 가격 제안 (선택)"):
        st.caption(
            "네이버쇼핑 검색 API가 2026-07-31부로 종료되어(대체 API 없음), 자동 시장가 조회는 더 이상 "
            "지원되지 않아요. 대신 네이버쇼핑 등에서 직접 검색해본 최저가를 키워드별로 아래 표에 입력하면, "
            "원가+배송비+목표마진율을 반영한 최소판매가와 비교해서 참고용 제안가를 계산해드려요. 픽투셀 "
            "'추가마진/목표대표가'를 자동으로 바꾸진 않으니, 여기 나온 제안가를 참고해서 위 카테고리 코드 "
            "옆의 추가마진을 직접 조정하세요."
        )
        price_col1, price_col2, price_col3 = st.columns(3)
        with price_col1:
            exchange_rate = st.number_input("환율 (위안당 원)", min_value=0.0, value=195.0, step=1.0)
        with price_col2:
            margin_rate_pct = st.number_input("목표 마진율(%)", min_value=0.0, value=30.0, step=5.0)
        with price_col3:
            undercut_pct = st.number_input("시장최저가 대비 목표(%)", min_value=50.0, max_value=100.0, value=95.0, step=1.0)

        keywords = (
            priced_df["검색키워드"].dropna().astype(str).unique().tolist()
            if "검색키워드" in priced_df.columns
            else []
        )
        keywords = [k for k in keywords if k]
        market_price_input_df = pd.DataFrame({"검색키워드": keywords, "시장최저가(직접입력,원)": [0] * len(keywords)})
        st.caption("키워드별로 네이버쇼핑 등에서 직접 확인한 최저가를 입력하세요 (모르면 0으로 두면 비교 없이 최소판매가만 제안돼요).")
        market_price_edited = st.data_editor(
            market_price_input_df,
            width='stretch',
            num_rows="fixed",
            key="market_price_editor",
        )

        if st.button("💰 가격 제안 계산"):
            market_by_keyword = dict(
                zip(market_price_edited["검색키워드"], market_price_edited["시장최저가(직접입력,원)"])
            )

            priced_rows = []
            for _, row in priced_df.iterrows():
                kw = row.get("검색키워드")
                market_min = market_by_keyword.get(kw) or None
                suggestion = pricing.suggest_competitive_price(
                    cost_cny=row["원가위안"],
                    exchange_rate=exchange_rate,
                    shipping_krw=row["배송비"],
                    margin_rate=margin_rate_pct / 100,
                    market_min_price=market_min,
                    undercut_ratio=undercut_pct / 100,
                )
                priced_rows.append(
                    {
                        "상품명": row["상품명"],
                        "검색키워드": kw,
                        "최소판매가(마진반영)": suggestion["최소판매가(마진반영)"],
                        "네이버시장최저가": suggestion["시장최저가"],
                        "제안판매가": suggestion["제안판매가"],
                        "경쟁력": suggestion["경쟁력"],
                        "메모": suggestion["메모"],
                    }
                )
            st.session_state["price_suggestion_df"] = pd.DataFrame(priced_rows)

        if "price_suggestion_df" in st.session_state:
            st.dataframe(st.session_state["price_suggestion_df"], width='stretch')

    exclude_risky = st.checkbox(
        "위험 상품은 제외하고 내보내기",
        value=True,
        help=(
            "'위험'(명확한 브랜드/통관 위험)만 제외돼요. '확인필요'(핑/펜/콘처럼 흔한 "
            "단어와 겹쳐서 오탐 가능성 있는 항목)는 자동 제외하지 않고 그대로 내보내되, "
            "메모 컬럼에 사유를 남겨서 직접 확인할 수 있게 해요."
        ),
    )

    export_df = priced_df[priced_df["위험여부"] != "위험"] if exclude_risky else priced_df
    confirm_needed_count = (export_df["위험여부"] == "확인필요").sum() if "위험여부" in export_df.columns else 0
    if confirm_needed_count > 0:
        st.warning(
            f"'확인필요' 상품 {confirm_needed_count}개는 제외 안 하고 그대로 내보내요. "
            "브랜드명이 흔한 단어와 겹쳐서 오탐일 수도 있으니, 표에서 위험사유 보고 실제 상품 페이지를 한 번 확인해보세요."
        )
    st.write(f"내보낼 상품 수: {len(export_df)}개 (픽투셀 파일 1개당 최대 500개)")

    blank_title_count = (export_df["한국어상품명(SEO)"] == "").sum() if "한국어상품명(SEO)" in export_df.columns else 0
    if blank_title_count > 0:
        st.info(
            f"한국어 상품명이 없는 상품 {blank_title_count}개는 엑셀에 상품명이 빈 칸으로 나가요 "
            "(중국어 원본은 안 씀). 픽투셀이 URL 기준으로 자체 상품명을 채워줄 수 있어요. "
            "위 표에서 직접 입력하거나 '한국어 상품명(SEO) 다시 생성' 버튼으로 재시도해도 돼요."
        )

    st.markdown("#### 카테고리 코드 (공통 적용 / 개별 매칭 안 된 상품용)")
    st.caption(
        "⚠️ 여러 키워드 일괄 처리로 수집했다면 키워드마다 이미 서로 다른 카테고리 코드가 위쪽 "
        "'⚖️ 무게 확인 및 배송비 계산' 표의 '쿠팡카테고리코드'/'스스카테고리코드' 컬럼에 개별로 들어가 있어요 "
        "(내보낼 때도 그 값이 우선 적용돼요) — 이 칸은 비어있는 게 정상이에요. "
        "여기 값을 채우면, 그 개별 매칭이 없는 상품에만 공통으로 적용돼요. "
        "단일 키워드로 검색했을 때는 이 칸이 자동 매칭 결과이니, 틀렸으면 직접 고치면 돼요 "
        "(픽투셀은 둘 다 있으면 쿠팡 기준으로 매칭)."
    )

    c1, c2 = st.columns(2)
    with c1:
        category_code_coupang = st.text_input("쿠팡 카테고리 코드", value=st.session_state.get("matched_category_쿠팡", ""))
    with c2:
        category_code_ss = st.text_input("스스 카테고리 코드", value=st.session_state.get("matched_category_스스", ""))

    if st.button("카테고리 코드 다시 매칭 (공통 적용용, 단일 키워드 검색에서만 의미 있음)"):
        korean_kw = st.session_state.get("scraped_korean_keyword", "")
        if not korean_kw or korean_kw == "(여러 키워드 일괄)":
            st.warning(
                "여러 키워드 일괄 처리 결과는 키워드마다 카테고리가 달라서 이 버튼으로 공통 재매칭할 수 없어요. "
                "위쪽 표의 '쿠팡카테고리코드'/'스스카테고리코드' 컬럼을 직접 확인/수정하세요."
            )
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

    add_to_archive_flag = st.checkbox(
        "내보낸 상품을 아카이브에 기록하기 (다음 검색 때 자동 중복제외)",
        value=True,
        help="테스트 중이라 같은 상품을 계속 다시 뽑아보고 싶으면 체크를 풀어두세요. 실제로 등록 끝낸 상품이면 체크해두는 게 좋아요.",
    )

    if st.button("픽투셀 양식 엑셀 만들기", type="primary"):
        if len(export_df) == 0:
            st.warning("내보낼 상품이 없어요.")
        else:
            export_rows = [
                {
                    "url": r["URL"],
                    "title": r.get("한국어상품명(SEO)") or "",
                    # 여러 키워드 일괄 처리 결과는 행마다 카테고리가 다를 수 있어서 그 값을
                    # 우선 쓰고, 없으면(단일 키워드 검색) 위의 수동 입력값을 그대로 쓴다.
                    "category_code_coupang": r.get("쿠팡카테고리코드") or category_code_coupang,
                    "category_code_ss": r.get("스스카테고리코드") or category_code_ss,
                    "extra_margin": r["추가마진"],
                    "memo": r["위험사유"] if r["위험여부"] != "안전" else "",
                }
                for _, r in export_df.iterrows()
            ]
            tmp_path = os.path.join(tempfile.gettempdir(), "픽투셀_업로드용.xlsx")
            try:
                export_to_pick2sell_template(export_rows, tmp_path)
                if add_to_archive_flag:
                    archive.add_to_archive(export_rows, keyword=st.session_state.get("scraped_keyword"))
                with open(tmp_path, "rb") as f:
                    st.download_button(
                        "픽투셀 업로드용 엑셀 다운로드",
                        data=f.read(),
                        file_name="픽투셀_업로드용.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                archive_msg = f"{len(export_rows)}개 아카이브에 기록됨" if add_to_archive_flag else "아카이브 기록 안 함, 다음에도 이 상품들 다시 뽑혀요"
                st.success(f"이 파일을 픽투셀 '엑셀로 일괄등록' 화면에 그대로 올리면 돼요. ({archive_msg})")
            except Exception as e:
                st.error(f"엑셀 생성 실패: {e}")

st.markdown("---")
with st.expander("🚫 개별 상품명 리스크 체크 (선택)"):
    text = st.text_input("상품명 또는 카테고리 입력", key="risk_check_text")
    if st.button("체크하기"):
        reasons = rules.check_risk(text)
        if reasons:
            level = rules.classify_risk(reasons)
            (st.warning if level == "확인필요" else st.error)(f"{level} 항목 발견:")
            for r, _ in reasons:
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
