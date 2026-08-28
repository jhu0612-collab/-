"""네이버 검색광고(SearchAd) API로 연관키워드의 실제 월간 검색량을 조회한다.

네이버 개발자센터/NAVER API HUB와는 완전히 별개의 서비스(searchad.naver.com, 광고주 가입
필요)이고 인증 방식도 다르다 - Client ID/Secret 헤더가 아니라, 요청마다 타임스탬프+시크릿키로
서명(HMAC-SHA256)한 값을 X-Signature 헤더에 실어 보내야 한다.

이 모듈은 SEO 제목 생성에 "감"이 아니라 실제 검색 데이터를 반영하기 위한 용도로 쓴다 -
연관키워드를 검색량 높은 순으로 뽑아서 lib/ai.py의 generate_seo_titles()에 넘기면,
AI가 서브키워드를 고를 때 이 목록을 우선 참고한다.
"""

import base64
import hashlib
import hmac
import time

import requests

BASE_URL = "https://api.naver.com"
KEYWORDS_URI = "/keywordstool"


def _sign(timestamp: str, method: str, uri: str, secret_key: str) -> str:
    message = f"{timestamp}.{method}.{uri}"
    digest = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _parse_count(value) -> int:
    """월간 검색량 필드는 10 미만이면 숫자 대신 "< 10" 문자열로 오는 경우가 있다."""
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("<"):
            return 5
        try:
            return int(stripped)
        except ValueError:
            return 0
    return 0


def get_related_keywords(api_key: str, secret_key: str, customer_id: str, keyword: str, top_n: int = 15):
    """keyword의 네이버 검색광고 연관키워드를 월간 검색량(PC+모바일) 합산 높은 순으로 반환한다.

    반환: (items, error). items는 [{"keyword": str, "검색량": int}, ...] (최대 top_n개).
    """
    if not api_key or not secret_key or not customer_id:
        return None, "네이버 검색광고 API 키/시크릿키/고객ID가 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not keyword:
        return None, "조회할 키워드가 없어요."

    timestamp = str(int(time.time() * 1000))
    headers = {
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": _sign(timestamp, "GET", KEYWORDS_URI, secret_key),
    }

    try:
        resp = requests.get(
            BASE_URL + KEYWORDS_URI,
            headers=headers,
            params={"hintKeywords": keyword, "showDetail": "1"},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        return None, f"검색광고 API 호출 실패: {e}"

    if not resp.ok:
        return None, f"검색광고 API 호출 실패 ({resp.status_code}): {resp.text[:300]}"

    try:
        data = resp.json()
    except ValueError:
        return None, "검색광고 API 응답을 해석하지 못했어요."

    items = []
    for row in data.get("keywordList", []):
        kw = row.get("relKeyword")
        if not kw:
            continue
        volume = _parse_count(row.get("monthlyPcQcCnt")) + _parse_count(row.get("monthlyMobileQcCnt"))
        items.append({"keyword": kw, "검색량": volume})

    items.sort(key=lambda x: -x["검색량"])
    return items[:top_n], None


def top_keyword_strings(items: list, exclude: str = None, limit: int = 12):
    """get_related_keywords() 결과에서 SEO 프롬프트에 바로 넘길 키워드 문자열 리스트를 만든다.

    exclude(메인키워드)와 완전히 같은 항목(띄어쓰기 무시)이나 중복은 제외한다."""
    if not items:
        return []
    exclude_norm = (exclude or "").replace(" ", "")
    seen = set()
    result = []
    for item in items:
        kw = item["keyword"].strip()
        norm = kw.replace(" ", "")
        if not kw or norm == exclude_norm or norm in seen:
            continue
        seen.add(norm)
        result.append(kw)
        if len(result) >= limit:
            break
    return result
