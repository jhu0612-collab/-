"""한국수출입은행 Open API로 실시간 환율(위안화) 조회."""

from datetime import datetime, timedelta

import requests

EXIM_API_URL = "https://oapi.koreaexim.go.kr/site/program/financial/exchangeJSON"


def get_cny_exchange_rate(auth_key: str, search_date: str = None):
    """위안화(CNH) 매매기준율을 조회한다. 실패하면 None과 이유 문자열을 반환한다.

    주말/공휴일은 환율 데이터가 없어서, 최근 7일 이내로 하루씩 앞당겨가며 재시도한다.
    """
    if not auth_key:
        return None, "환율 API 키가 입력되지 않았어요. 사이드바에서 입력해주세요."

    date = datetime.strptime(search_date, "%Y%m%d") if search_date else datetime.now()

    for _ in range(7):
        date_str = date.strftime("%Y%m%d")
        try:
            resp = requests.get(
                EXIM_API_URL,
                params={"authkey": auth_key, "searchdate": date_str, "data": "AP01"},
                timeout=10,
            )
            resp.raise_for_status()
            rows = resp.json()
        except Exception as e:
            return None, f"환율 API 호출 실패: {e}"

        for row in rows:
            if row.get("cur_unit") == "CNH":
                rate_str = row.get("deal_bas_r", "").replace(",", "")
                if rate_str:
                    return float(rate_str), date_str

        date -= timedelta(days=1)

    return None, "최근 7일 내 위안화 환율 데이터를 찾지 못했어요."
