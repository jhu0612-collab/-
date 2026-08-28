"""여러 키워드를 한 번에 처리하는 배치 파이프라인.

Home.py의 "검색→수집→카테고리매칭" 단일 키워드 흐름과 같은 단계(번역 → 타오바오
검색/수집 → 서비스성/주문제작/전압/미끼가격/중복/관련성 필터링 → 카테고리 코드
매칭 → SEO 제목 생성)를 한 키워드씩 밟되, Streamlit UI 호출(st.info 등) 없이
결과와 로그 문자열만 반환한다. 여러 키워드를 순서대로 돌려서 결과를 하나로
합치는 용도로 쓴다.
"""

import pandas as pd

from lib import ai, apify_scraper, category_code, naver_searchad, rules, translate


def match_categories(korean_keyword: str, anthropic_key: str):
    """반환: {system: (code, 설명, 추정여부)}. Home.py의 _auto_match_categories와 동일한 로직."""
    results = {}
    for system in ["쿠팡", "스스"]:
        candidates = category_code.find_candidates(korean_keyword, system=system)
        if candidates:
            code, error = ai.match_category_code(anthropic_key, korean_keyword, candidates)
            if error:
                results[system] = (None, error, False)
            else:
                path = dict(candidates)[code]
                results[system] = (code, path, False)
        else:
            code, info = ai.guess_category_fallback(anthropic_key, korean_keyword, system)
            results[system] = (code, info, True) if code else (None, info, False)
    return results


def run_single_keyword(
    keyword_input: str,
    *,
    min_price: float,
    max_price: float,
    max_items: int,
    tmall_only: bool,
    exclude_bait_price: bool,
    enrich_with_details: bool,
    anthropic_key: str,
    apify_token: str,
    archived_urls: set,
    naver_searchad_api_key: str = None,
    naver_searchad_secret_key: str = None,
    naver_searchad_customer_id: str = None,
):
    """키워드 하나를 번역부터 SEO 제목 생성까지 전부 처리해서 결과 dict를 반환한다.

    반환 dict:
        df: 처리된 DataFrame (실패하거나 결과 0건이면 None)
        chinese_keyword, korean_keyword: 검색/카테고리매칭에 쓰인 키워드
        category_results: match_categories()의 반환값 (df가 None이면 None)
        log: 진행 로그 문자열 리스트 (성공/실패/필터링 개수 등)
        error: 치명적 에러가 있으면 문자열, 없으면 None
    """
    log = []
    result = {"df": None, "chinese_keyword": None, "korean_keyword": None, "category_results": None, "log": log, "error": None}

    if translate.contains_hangul(keyword_input):
        chinese_keyword, t_error = translate.translate_ko_to_zh(keyword_input, anthropic_key)
        korean_keyword = keyword_input.replace(" ", "")
    else:
        chinese_keyword = keyword_input
        korean_keyword, t_error = translate.translate_zh_to_ko(keyword_input, anthropic_key)

    if t_error:
        result["error"] = f"번역 실패: {t_error}"
        return result

    result["chinese_keyword"] = chinese_keyword
    result["korean_keyword"] = korean_keyword

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
        result["error"] = f"Apify 검색 실패: {error}"
        return result
    if not items:
        result["error"] = "검색 결과가 없어요."
        return result

    actor_error = apify_scraper.find_actor_error(items)
    if actor_error:
        result["error"] = f"Apify 액터 에러: {actor_error}"
        return result

    rows = apify_scraper.to_rows(items)
    if not rows:
        result["error"] = "실제 상품(URL/가격 있는)이 하나도 없었어요."
        return result

    df = pd.DataFrame(rows)
    before = len(df)

    df = df[~df["상품명"].apply(rules.is_service_listing)].reset_index(drop=True)
    log.append(f"서비스성 상품 제외: {before - len(df)}개")
    before = len(df)

    custom_order_mask = df["상품명"].apply(rules.is_custom_order_listing)
    if "_주문제작속성감지" in df.columns:
        custom_order_mask = custom_order_mask | df["_주문제작속성감지"]
    df = df[~custom_order_mask].reset_index(drop=True)
    df = df.drop(columns=["_주문제작속성감지"], errors="ignore")
    log.append(f"주문제작 상품 제외: {before - len(df)}개")
    before = len(df)

    if "_110V전용" in df.columns:
        df = df[~df["_110V전용"]].reset_index(drop=True)
    df = df.drop(columns=["_110V전용"], errors="ignore")
    log.append(f"110V 전용 제외: {before - len(df)}개")

    if exclude_bait_price and "가격편차배수" in df.columns:
        before = len(df)
        bait_mask = df.apply(
            lambda r: apify_scraper.is_bait_price_suspected(r["최저가위안"], r["가격편차배수"]), axis=1
        )
        df = df[~bait_mask].reset_index(drop=True)
        log.append(f"미끼가격 의심 제외: {before - len(df)}개")

    before = len(df)
    df = df[~df["URL"].isin(archived_urls)].reset_index(drop=True)
    log.append(f"아카이브 중복 제외: {before - len(df)}개")

    if len(df) > 0:
        relevance, relevance_error = ai.check_relevance(anthropic_key, df["상품명"].tolist(), korean_keyword)
        if relevance_error:
            log.append(f"관련성 확인 실패(건너뜀): {relevance_error}")
        else:
            before = len(df)
            df = df[pd.Series(relevance, index=df.index)].reset_index(drop=True)
            log.append(f"검색어 무관 상품 제외: {before - len(df)}개")

    if len(df) == 0:
        result["error"] = "필터링 후 신규 상품이 0개예요."
        return result

    df["예상무게(kg)"] = 1.0
    df.insert(0, "선택", False)
    df.insert(1, "검색키워드", korean_keyword)

    category_results = match_categories(korean_keyword, anthropic_key)
    df["쿠팡카테고리코드"] = category_results.get("쿠팡", (None, None, False))[0] or ""
    df["스스카테고리코드"] = category_results.get("스스", (None, None, False))[0] or ""
    result["category_results"] = category_results

    related_keywords = None
    if naver_searchad_api_key and naver_searchad_secret_key and naver_searchad_customer_id:
        rel_items, rel_error = naver_searchad.get_related_keywords(
            naver_searchad_api_key, naver_searchad_secret_key, naver_searchad_customer_id, korean_keyword
        )
        if rel_error:
            log.append(f"검색광고 연관키워드 조회 실패(건너뜀): {rel_error}")
        else:
            related_keywords = naver_searchad.top_keyword_strings(rel_items, exclude=korean_keyword)

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
        log.append(f"SEO 제목 생성 실패: {seo_error}")
    else:
        df["한국어상품명(SEO)"] = seo_titles
        df["제목글자수"] = [len(t) for t in seo_titles]
        if seo_error:
            log.append(f"SEO 제목 일부 실패: {seo_error}")

    log.append(f"최종 수집: {len(df)}개")
    result["df"] = df
    return result
