"""셀러라이프 엑셀 필터링 규칙 + 지재권/통관 리스크 체크.

기준 출처: 해구대 강의(디노픽스 '닥등' 필터 기준) 정리본.
"""

import os
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
BLACKLIST_PATH = os.path.join(DATA_DIR, "blacklist.txt")
CUSTOMS_EXCLUDED_PATH = os.path.join(DATA_DIR, "customs_excluded.txt")
SERVICE_EXCLUDED_PATH = os.path.join(DATA_DIR, "service_excluded.txt")

DEFAULT_MIN_SEARCH = 300
DEFAULT_MAX_SEARCH = 5000
DEFAULT_MIN_OVERSEAS_SHIPPING_RATIO = 0.2
DEFAULT_MIN_OVERSEAS_REVIEW_AVG = 1


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """엑셀 헤더에 섞인 줄바꿈 문자를 제거해서 컬럼명을 다루기 쉽게 만든다."""
    df = df.copy()
    df.columns = [str(c).replace("\n", "") for c in df.columns]
    return df


REQUIRED_COLUMNS = [
    "키워드",
    "카테고리",
    "브랜드키워드",
    "최근1개월검색량",
    "쿠팡해외배송비율",
    "쿠팡해외배송평균리뷰수",
]


def check_columns(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    return missing


def filter_candidates(
    df: pd.DataFrame,
    min_search=DEFAULT_MIN_SEARCH,
    max_search=DEFAULT_MAX_SEARCH,
    min_overseas_ratio=DEFAULT_MIN_OVERSEAS_SHIPPING_RATIO,
    min_overseas_review_avg=DEFAULT_MIN_OVERSEAS_REVIEW_AVG,
    exclude_brand=True,
) -> pd.DataFrame:
    df = normalize_columns(df)
    missing = check_columns(df)
    if missing:
        raise ValueError(f"엑셀에 다음 컬럼이 없어요: {missing}")

    mask = (
        (df["최근1개월검색량"] >= min_search)
        & (df["최근1개월검색량"] <= max_search)
        & (df["쿠팡해외배송비율"] >= min_overseas_ratio)
        & (df["쿠팡해외배송평균리뷰수"] >= min_overseas_review_avg)
    )
    if exclude_brand:
        mask &= df["브랜드키워드"].astype(str).str.upper() == "X"

    result = df[mask].sort_values("최근1개월검색량", ascending=False)
    return result


def _load_lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]


def load_blacklist():
    return _load_lines(BLACKLIST_PATH)


def load_customs_excluded():
    return _load_lines(CUSTOMS_EXCLUDED_PATH)


def load_service_excluded():
    return _load_lines(SERVICE_EXCLUDED_PATH)


def is_service_listing(title: str, service_excluded=None) -> bool:
    """출장설치/조립 등 서비스성 상품(해외배송 자체가 불가능한 상품)인지 확인한다."""
    service_excluded = service_excluded if service_excluded is not None else load_service_excluded()
    text_lower = str(title).lower()
    return any(word.lower() in text_lower for word in service_excluded)


def check_risk(text: str, blacklist=None, customs_excluded=None):
    """상품명/카테고리 문자열 하나를 검사해서 위험 사유 리스트를 반환한다."""
    blacklist = blacklist if blacklist is not None else load_blacklist()
    customs_excluded = customs_excluded if customs_excluded is not None else load_customs_excluded()

    reasons = []
    text_lower = str(text).lower()
    for word in blacklist:
        if word.lower() in text_lower:
            reasons.append(f"지재권/브랜드 위험 키워드 포함: '{word}'")
    for word in customs_excluded:
        if word.lower() in text_lower:
            reasons.append(f"목록통관 배제 대상 가능성: '{word}' (정식통관 필요 여부 확인 필요)")
    return reasons


def check_risk_bulk(items):
    """[(식별자, 텍스트), ...] 리스트를 받아 위험여부 표를 만든다."""
    blacklist = load_blacklist()
    customs_excluded = load_customs_excluded()
    rows = []
    for identifier, text in items:
        reasons = check_risk(text, blacklist, customs_excluded)
        rows.append(
            {
                "항목": identifier,
                "위험여부": "위험" if reasons else "안전",
                "사유": " / ".join(reasons) if reasons else "",
            }
        )
    return pd.DataFrame(rows)
