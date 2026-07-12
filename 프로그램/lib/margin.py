"""원가(위안) + 환율 + 배송비 + 마진율을 조합해 최종 판매가를 계산한다.

핵심 원칙(강의 기준): 배송비는 마진율(%)이 아니라 정액으로 최종가에 더한다.
"""

from lib.shipping import calculate_shipping

DEFAULT_MARGIN_RATE = 0.4
DEFAULT_EXTRA_MARGIN = 10000


def calculate_final_price(
    cost_cny: float,
    exchange_rate: float,
    weight_kg: float,
    girth_cm: float = None,
    shipping_method: str = "해운",
    packaging_type: str = "일반",
    margin_rate: float = DEFAULT_MARGIN_RATE,
    extra_margin: float = DEFAULT_EXTRA_MARGIN,
):
    cost_krw = cost_cny * exchange_rate
    shipping = calculate_shipping(
        weight_kg=weight_kg,
        girth_cm=girth_cm,
        shipping_method=shipping_method,
        packaging_type=packaging_type,
    )
    margin_applied = cost_krw * (1 + margin_rate)
    final_price = margin_applied + shipping["배송비합계"] + extra_margin

    return {
        "원가(위안)": cost_cny,
        "환율": exchange_rate,
        "원가(원)": round(cost_krw),
        "마진적용가(원)": round(margin_applied),
        "배송비상세": shipping,
        "추가마진(정액)": extra_margin,
        "최종판매가": round(final_price),
    }
