"""네이버 검색 오픈API(쇼핑)를 호출해서 국내 시장가격을 확인한다.

네이버 개발자센터(developers.naver.com)에서 애플리케이션을 등록하면 Client ID/Secret을
받을 수 있다. 이 API는 정렬 옵션이 정확도순(sim)/날짜순(date)/가격오름차순(asc)/
가격내림차순(dsc) 뿐이고, 리뷰수·판매량 같은 필드는 응답에 아예 없다 - "잘 팔리는
상품 정렬"은 이 API로는 안 되고, 여기서는 순수하게 "이 키워드로 국내에 실제 팔리는
가격대가 어느 정도인지" 확인하는 용도로만 쓴다.
"""

import re
import statistics

import requests

SEARCH_URL = "https://openapi.naver.com/v1/search/shop.json"

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(text: str) -> str:
    """네이버 쇼핑 검색 결과 title엔 검색어 강조용 <b> 태그가 섞여있어서 제거한다."""
    return _TAG_RE.sub("", text or "")


def search_products(client_id: str, client_secret: str, query: str, display: int = 40, sort: str = "sim"):
    """네이버쇼핑에서 query로 검색한 상품 목록을 반환한다.

    반환: (items, error). items는 [{"title", "link", "lprice", "hprice", "mall_name",
    "category1"..4, "brand", "maker"}, ...] 형태.
    """
    if not client_id or not client_secret:
        return None, "네이버 API Client ID/Secret이 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not query or not query.strip():
        return None, "검색할 키워드가 비어있어요."

    try:
        resp = requests.get(
            SEARCH_URL,
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
            },
            params={"query": query, "display": min(max(display, 1), 100), "sort": sort},
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return None, f"네이버쇼핑 API 호출 실패: {e}"

    if not resp.ok:
        return None, f"네이버쇼핑 API 호출 실패 ({resp.status_code}): {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return None, "네이버쇼핑 API 응답을 해석하지 못했어요."

    items = []
    for raw in data.get("items", []):
        try:
            lprice = float(raw.get("lprice")) if raw.get("lprice") else None
        except (TypeError, ValueError):
            lprice = None
        items.append(
            {
                "title": _strip_tags(raw.get("title", "")),
                "link": raw.get("link"),
                "lprice": lprice,
                "mall_name": raw.get("mallName"),
                "brand": raw.get("brand") or None,
                "maker": raw.get("maker") or None,
                "category1": raw.get("category1"),
                "category2": raw.get("category2"),
                "category3": raw.get("category3"),
                "category4": raw.get("category4"),
            }
        )
    return items, None


def summarize_market_price(items: list):
    """search_products 결과에서 최저가/중간값/판매몰 수를 요약한다 (원 단위, lprice가 0이거나
    없는 항목은 가격 미상으로 보고 제외한다). 유효 가격이 하나도 없으면 None을 반환한다."""
    prices = [it["lprice"] for it in items if it.get("lprice") and it["lprice"] > 0]
    if not prices:
        return None

    return {
        "최저가": min(prices),
        "중간값": statistics.median(prices),
        "최고가": max(prices),
        "샘플수": len(prices),
        "판매몰수": len({it["mall_name"] for it in items if it.get("mall_name")}),
    }
