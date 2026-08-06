"""Apify의 타오바오/티몰 검색 액터(zen-studio/taobao-search-scraper)를 호출한다."""

import re

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
    enrich_with_details: bool = False,
):
    if not api_token:
        return None, "Apify API 토큰이 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not keyword or not keyword.strip():
        return None, "검색할 키워드가 비어있어요."
    if max_items < 10:
        return None, "최대 수집 개수는 10개 이상이어야 해요 (액터 제한)."

    payload = {
        "enrichWithDetails": enrich_with_details,
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


_PRICE_RANGE_FIELD_CANDIDATES = ["priceRange", "skuPriceRange", "price_range"]
_MIN_MAX_FIELD_CANDIDATES = [
    ("priceMin", "priceMax"),
    ("minSkuPrice", "maxSkuPrice"),
    ("lowestPrice", "highestPrice"),
]
_RANGE_STR_RE = re.compile(r"[¥￥]?\s*([\d.]+)\s*[-~]\s*[¥￥]?\s*([\d.]+)")


def _parse_price_range(item: dict):
    """옵션별 최저~최고 가격을 알아낼 수 있으면 (최저가, 최고가)를 반환하고, 못 찾으면 (None, None).

    액터가 정확히 어떤 필드명으로 가격범위를 주는지 문서로 확인이 안 돼서, 자주 쓰이는
    후보 필드명 여러 개를 시도해본다. 다 없으면 그냥 None을 반환하고 넘어간다.
    """
    for field in _PRICE_RANGE_FIELD_CANDIDATES:
        value = item.get(field)
        if isinstance(value, str):
            m = _RANGE_STR_RE.search(value)
            if m:
                try:
                    return float(m.group(1)), float(m.group(2))
                except ValueError:
                    pass

    for min_field, max_field in _MIN_MAX_FIELD_CANDIDATES:
        min_v, max_v = item.get(min_field), item.get(max_field)
        if min_v is not None and max_v is not None:
            try:
                return float(min_v), float(max_v)
            except (TypeError, ValueError):
                pass

    return None, None


def is_bait_price_suspected(min_price: float, ratio: float) -> bool:
    """미끼가격(제일 싼 옵션만 대표가로 노출) 의심 여부를 판단한다.

    옵션이 많은 상품은 사이즈/색상 차이만으로도 2~3배 편차가 흔하기 때문에,
    편차만으로 판단하면 정상 상품까지 대량으로 오탐된다. 그래서 두 조건 중
    하나에 해당할 때만 의심으로 본다.
    1) 최저가 자체가 비정상적으로 싸면서(15위안 이하, 약 3천원) 편차도 3배 이상인 경우
       (전형적인 "1위안짜리 옵션 하나 끼워넣기" 패턴)
    2) 최저가와 무관하게 편차가 8배 이상으로 극단적인 경우
    """
    if min_price is None or ratio is None:
        return False
    return (min_price <= 15 and ratio >= 3.0) or ratio >= 8.0


_CUSTOM_ATTR_NEGATIVE_MARKERS = ("不支持", "不可", "否", "无需", "非")


def _is_positive_custom_attribute(name: str, value: str) -> bool:
    name, value = str(name), str(value)
    if "定制" not in name and "定做" not in name:
        return False
    return not any(marker in value for marker in _CUSTOM_ATTR_NEGATIVE_MARKERS)


def is_custom_order_from_attributes(attributes) -> bool:
    """enrichWithDetails로 받은 attributes(상품 속성) 목록에서 주문제작 여부를 판단한다.

    타오바오는 "是否可定制"/"尺寸定制" 같은 속성명에 "支持定制"/"是" 같은 값을 넣어서
    이 상품이 치수 등을 매번 맞춰야 하는 주문제작 상품임을 표시하는 경우가 있다. 제목엔
    이 정보가 안 나오고, enrichWithDetails를 켰을 때만 이 attributes로 내려온다.
    """
    for attr in attributes or []:
        if not isinstance(attr, dict):
            continue
        if _is_positive_custom_attribute(attr.get("name", ""), attr.get("value", "")):
            return True
    return False


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

        row = {
            "상품명": item.get("title"),
            "원가위안": price,
            "URL": url,
            "셀러평점": item.get("sellerGoodrat"),
            "판매량": item.get("salesSignal"),
            "재고": item.get("frontStock"),
            "_주문제작속성감지": is_custom_order_from_attributes(item.get("attributes")),
        }

        min_price, max_price = _parse_price_range(item)
        if min_price is None or max_price is None or min_price <= 0 or max_price < min_price:
            # 옵션별 가격범위 필드를 못 찾았으면, 대표가 하나를 최저/최고에 그대로 넣어서
            # 컬럼이 항상 보이게 한다 (이 경우 편차배수는 항상 1.0).
            min_price, max_price = price, price
        row["최저가위안"] = min_price
        row["최고가위안"] = max_price
        row["가격편차배수"] = round(max_price / min_price, 1) if min_price > 0 else 1.0

        rows.append(row)
    return rows
