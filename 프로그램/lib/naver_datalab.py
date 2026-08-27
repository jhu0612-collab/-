"""네이버 데이터랩(쇼핑인사이트) API로 이미 갖고 있는 후보 키워드들의 최근 검색 트렌드를 비교한다.

주의: 이 API는 "이 분야에서 요즘 뜨는 키워드가 뭐야?"처럼 새 키워드를 발굴해주는 게
아니다. 비교하고 싶은 키워드 묶음(최대 5개)을 직접 넣어야 하고, 그 키워드들 사이의
상대적 검색량 추이(그래프용 지수, 절대 검색량 아님)만 돌려준다. 그래서 여기서는
"발굴"이 아니라, 셀러라이프 등에서 이미 뽑아낸 후보 키워드들을 "최근에 뜨는 중인지
vs 시들해지는 중인지" 기준으로 재정렬하는 용도로 쓴다.
"""

import requests

DATALAB_URL = "https://openapi.naver.com/v1/datalab/shopping/category/keywords"
_MAX_KEYWORDS_PER_CALL = 5


def get_keyword_trend(
    client_id: str,
    client_secret: str,
    category_code: str,
    keywords: list,
    start_date: str,
    end_date: str,
    time_unit: str = "week",
):
    """category_code 분야 안에서 keywords(최대 5개) 각각의 기간별 상대 검색 지수를 반환한다.

    start_date/end_date: "YYYY-MM-DD" 형식. time_unit: "date"/"week"/"month".
    반환: (results, error). results는 {"results": [{"title": 키워드, "data": [{"period":.., "ratio":..}, ...]}, ...]}
    형태의 API 원본 응답을 그대로 넘긴다(호출 쪽에서 ratio 평균/최근값 등으로 가공).
    """
    if not client_id or not client_secret:
        return None, "네이버 API Client ID/Secret이 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not keywords:
        return None, "비교할 키워드가 없어요."
    if len(keywords) > _MAX_KEYWORDS_PER_CALL:
        return None, f"데이터랩은 한 번에 최대 {_MAX_KEYWORDS_PER_CALL}개 키워드까지만 비교할 수 있어요."

    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        "category": category_code,
        "keyword": [{"name": kw, "param": [kw]} for kw in keywords],
    }

    try:
        resp = requests.post(
            DATALAB_URL,
            headers={
                "X-Naver-Client-Id": client_id,
                "X-Naver-Client-Secret": client_secret,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        return None, f"데이터랩 API 호출 실패: {e}"

    if not resp.ok:
        return None, f"데이터랩 API 호출 실패 ({resp.status_code}): {resp.text[:300]}"

    try:
        return resp.json(), None
    except ValueError:
        return None, "데이터랩 API 응답을 해석하지 못했어요."


def rank_keywords_by_recent_trend(
    client_id: str, client_secret: str, category_code: str, keywords: list, weeks: int = 8
):
    """keywords를 5개씩 나눠서 최근 `weeks`주 트렌드를 조회하고, 최근 구간 평균 지수가
    높은 순으로 정렬한 [(keyword, 최근평균지수), ...]를 반환한다.

    5개 초과분은 여러 번 호출해서 합친다(데이터랩 자체 비교는 5개 단위로만 되고,
    서로 다른 호출끼리는 지수 스케일이 다를 수 있어서 절대비교가 아니라 참고용이다).
    """
    import datetime

    end = datetime.date.today()
    start = end - datetime.timedelta(weeks=weeks)
    start_date, end_date = start.isoformat(), end.isoformat()

    ranked = []
    errors = []
    for i in range(0, len(keywords), _MAX_KEYWORDS_PER_CALL):
        batch = keywords[i : i + _MAX_KEYWORDS_PER_CALL]
        data, error = get_keyword_trend(
            client_id, client_secret, category_code, batch, start_date, end_date, time_unit="week"
        )
        if error:
            errors.append(error)
            for kw in batch:
                ranked.append((kw, None))
            continue
        for result in data.get("results", []):
            points = result.get("data", [])
            avg_ratio = sum(p.get("ratio", 0) for p in points) / len(points) if points else 0
            ranked.append((result.get("title"), avg_ratio))

    ranked.sort(key=lambda x: (x[1] is None, -(x[1] or 0)))
    return ranked, ("; ".join(errors) if errors else None)
