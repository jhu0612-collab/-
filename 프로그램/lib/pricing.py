"""원가+배송비+마진율과 국내 시장가를 비교해서 경쟁력있는 목표판매가를 제안한다.

픽투셀 자체 마진 엔진과는 별개로, "이 가격 밑으로는 마진이 안 남는다"는 하한선과
"시장에 이미 깔린 가격"을 비교해서 참고용 제안가를 계산하는 순수 계산 로직이다.
마진율은 원가 대비 붙이는 마크업 방식으로 계산한다 (판매가 = 총원가 × (1+마진율)).
"""


def suggest_competitive_price(
    cost_cny: float,
    exchange_rate: float,
    shipping_krw: float,
    margin_rate: float,
    market_min_price: float = None,
    undercut_ratio: float = 0.95,
):
    """반환: dict — 원가/최소판매가/시장최저가/제안판매가/경쟁력 여부/설명 메모.

    market_min_price가 없으면(네이버쇼핑에서 못 찾은 경우) 최소판매가를 그대로 제안하고
    "경쟁력" 판단은 생략한다. undercut_ratio는 시장 최저가 대비 몇 %로 맞출지(기본 95%).
    """
    cost_krw = cost_cny * exchange_rate
    total_cost_krw = cost_krw + shipping_krw
    min_sell_price = total_cost_krw * (1 + margin_rate)

    result = {
        "원가원": round(cost_krw),
        "총원가(배송비포함)": round(total_cost_krw),
        "최소판매가(마진반영)": round(min_sell_price),
        "시장최저가": round(market_min_price) if market_min_price else None,
        "제안판매가": round(min_sell_price),
        "경쟁력": "판단불가",
        "메모": "시장가 데이터 없음 - 최소판매가 그대로 제안",
    }

    if not market_min_price:
        return result

    target_price = market_min_price * undercut_ratio
    if target_price >= min_sell_price:
        result["제안판매가"] = round(target_price)
        result["경쟁력"] = "우위"
        result["메모"] = f"시장최저가의 {round(undercut_ratio * 100)}%로 맞춰도 마진이 남아요."
    else:
        result["제안판매가"] = round(min_sell_price)
        result["경쟁력"] = "열위"
        result["메모"] = "시장가에 맞추면 마진이 안 남아서, 마진 확보되는 최소판매가로 제안했어요 (시장가보다 비쌀 수 있어요)."

    return result
