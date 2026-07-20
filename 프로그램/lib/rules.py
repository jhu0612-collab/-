"""셀러라이프 엑셀 필터링 규칙 + 지재권/통관 리스크 체크.

기준 출처: 해구대 강의(디노픽스 '닥등' 필터 기준) 정리본.
"""

import os
import re

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
BLACKLIST_PATH = os.path.join(DATA_DIR, "blacklist.txt")
CUSTOMS_EXCLUDED_PATH = os.path.join(DATA_DIR, "customs_excluded.txt")
SERVICE_EXCLUDED_PATH = os.path.join(DATA_DIR, "service_excluded.txt")
AMBIGUOUS_BRAND_WORDS_PATH = os.path.join(DATA_DIR, "ambiguous_brand_words.txt")

_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9&.\-' ]+")

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


def load_ambiguous_brand_words():
    return {w.lower() for w in _load_lines(AMBIGUOUS_BRAND_WORDS_PATH)}


def is_service_listing(title: str, service_excluded=None) -> bool:
    """출장설치/조립 등 서비스성 상품(해외배송 자체가 불가능한 상품)인지 확인한다."""
    service_excluded = service_excluded if service_excluded is not None else load_service_excluded()
    text_lower = str(title).lower()
    return any(word.lower() in text_lower for word in service_excluded)


_PUNCT_STRIP_RE = re.compile(r"^[^\w가-힣]+|[^\w가-힣]+$")


def _word_matches(word: str, text_lower: str) -> bool:
    """영문/숫자로만 된 단어(K2, MI, CJ 등)는 단어경계로 매칭해서 다른 단어에
    우연히 포함된 경우(premium 안의 mi 등)의 오탐을 줄인다.

    한글 2글자 이하 단어("핑", "카", "맥", "펜" 등)는 부분일치로 검사하면
    "캠핑"(핑), "카고팬츠"(카), "맥주"(맥), "볼펜"(펜)처럼 완전히 무관한 단어
    안에도 걸려버려서, 띄어쓰기로 구분된 독립된 토큰일 때만 매칭한다.

    그 외 한글 단어(3글자 이상, 예: "나이키")는 한국어 상품명이 띄어쓰기 없이
    붙어있는 경우가 많아서("나이키운동화") 기존처럼 부분일치로 검사한다."""
    word_lower = word.lower()
    if _LATIN_WORD_RE.fullmatch(word):
        pattern = r"(?<!\w)" + re.escape(word_lower) + r"(?!\w)"
        return re.search(pattern, text_lower) is not None
    if len(word) <= 2:
        tokens = (_PUNCT_STRIP_RE.sub("", t) for t in text_lower.split())
        return word_lower in tokens
    return word_lower in text_lower


def check_risk(text: str, blacklist=None, customs_excluded=None, ambiguous_words=None):
    """상품명/카테고리 문자열 하나를 검사해서 [(사유, 확인필요여부: bool), ...] 리스트를 반환한다.

    확인필요여부가 True인 항목은 브랜드명이면서 동시에 흔한 일반 단어와도 겹치는
    경우("핑" vs "쇼핑", "펜" vs "볼펜" 등)라서, 자동으로 위험 처리하지 않고
    사람이 한 번 더 확인하도록 구분해둔다.
    """
    blacklist = blacklist if blacklist is not None else load_blacklist()
    customs_excluded = customs_excluded if customs_excluded is not None else load_customs_excluded()
    ambiguous_words = ambiguous_words if ambiguous_words is not None else load_ambiguous_brand_words()

    reasons = []
    text_lower = str(text).lower()
    for word in blacklist:
        if _word_matches(word, text_lower):
            # 한글 1~2글자짜리 단어("카", "맥", "펜", "후" 등)는 브랜드명이자
            # 동시에 다른 단어 안에 흔히 섞여 나오는 음절이라, 명시적으로 등록
            # 안 해도 항상 확인필요로 분류한다 (영문 약어는 단어경계 매칭이라
            # 이미 오탐 위험이 낮아서 제외).
            is_short_hangul = len(word) <= 2 and not _LATIN_WORD_RE.fullmatch(word)
            is_ambiguous = word.lower() in ambiguous_words or is_short_hangul
            hint = " (일반 단어와 겹칠 수 있어 실제 브랜드 제품인지 직접 확인 필요)" if is_ambiguous else ""
            reasons.append((f"지재권/브랜드 위험 키워드 포함: '{word}'{hint}", is_ambiguous))
    for word in customs_excluded:
        if _word_matches(word, text_lower):
            reasons.append((f"목록통관 배제 대상 가능성: '{word}' (정식통관 필요 여부 확인 필요)", False))
    return reasons


def classify_risk(reasons) -> str:
    """check_risk()가 반환한 [(사유, 확인필요여부), ...]를 안전/확인필요/위험 중 하나로 분류한다."""
    if not reasons:
        return "안전"
    if any(not is_ambiguous for _, is_ambiguous in reasons):
        return "위험"
    return "확인필요"


def check_risk_bulk(items):
    """[(식별자, 텍스트), ...] 리스트를 받아 위험여부 표를 만든다."""
    blacklist = load_blacklist()
    customs_excluded = load_customs_excluded()
    ambiguous_words = load_ambiguous_brand_words()
    rows = []
    for identifier, text in items:
        reasons = check_risk(text, blacklist, customs_excluded, ambiguous_words)
        rows.append(
            {
                "항목": identifier,
                "위험여부": classify_risk(reasons),
                "사유": " / ".join(r for r, _ in reasons) if reasons else "",
            }
        )
    return pd.DataFrame(rows)
