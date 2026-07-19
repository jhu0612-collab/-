"""Apify의 타오바오/티몰 검색 액터(zen-studio/taobao-search-scraper)를 호출한다."""

import requests

ACTOR_ID = "PsAKYWM55HG4AHXjK"
RUN_SYNC_URL = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"


def search_products(
    api_token: str,
    keyword: str,
    min_price: float = None,
    max_price: float = None,
    max_items: int = 50,
    tmall_only: bool = False,
):
    if not api_token:
        return None, "Apify API 토큰이 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not keyword or not keyword.strip():
        return None, "검색할 키워드가 비어있어요."
    if max_items < 10:
        return None, "최대 수집 개수는 10개 이상이어야 해요 (액터 제한)."

    payload = {
        "enrichWithDetails": False,
        "fetchReviews": False,
        "keyword": keyword,
        "maxItems": max_items,
        "tmallOnly": tmall_only,
    }
    if min_price is not None:
        payload["minPrice"] = min_price
    if max_price is not None:
        payload["maxPrice"] = max_price

    try:
        resp = requests.post(
            RUN_SYNC_URL,
            params={"token": api_token},
            json=payload,
            timeout=300,
        )
        if not resp.ok:
            return None, f"Apify 호출 실패 ({resp.status_code}): {resp.text[:500]}"
        return resp.json(), None
    except requests.exceptions.Timeout:
        return None, "Apify 응답이 너무 오래 걸려요. maxItems를 줄여서 다시 시도해보세요."
    except Exception as e:
        return None, f"Apify 호출 실패: {e}"


def find_actor_error(items):
    """Apify 액터가 정상 상품 대신 자체 에러 객체(예: 무료 체험 소진)를 반환했는지 확인한다.

    이런 경우 결과가 0건이 아니라 {"error": ..., "message": ...} 형태의 항목이
    섞여서 오기 때문에, 일반적인 '결과 없음'과 구분해서 안내해야 한다.
    """
    for item in items:
        if isinstance(item, dict) and item.get("error"):
            return item.get("message") or item.get("error")
    return None


def to_rows(items):
    """스크래핑 결과를 우리 프로그램에서 다루기 쉬운 표 형태로 정리한다.

    URL이나 가격이 없는 항목(빈 결과/에러성 응답)은 상품이 아니므로 걸러낸다.
    """
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue

        url = item.get("url")
        price = item.get("discountedPriceFromSearch") or item.get("price")
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None

        if not url or price is None:
            continue

        rows.append(
            {
                "상품명": item.get("title"),
                "원가위안": price,
                "URL": url,
                "셀러평점": item.get("sellerGoodrat"),
                "판매량": item.get("salesSignal"),
                "재고": item.get("frontStock"),
            }
        )
    return rows
