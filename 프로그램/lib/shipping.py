"""동백국제물류 배송비 계산 (2026년 요금표 기준).

사용자가 제공한 공식 요금표에서 역산한 규칙:
- 0.5kg: 5,200원 / 1.0kg: 6,000원 / 이후 0.5kg당 +1,350원 (0% 세율 기준)
- 10% 세율 = 0% 세율 금액의 1.1배

요금표가 개정되면 이 파일의 상수만 갱신하면 된다.
"""

import math

BASE_FIRST_STEP_KG = 0.5
BASE_FIRST_STEP_FEE = 5200
BASE_SECOND_STEP_KG = 1.0
BASE_SECOND_STEP_FEE = 6000
BASE_STEP_KG = 0.5
BASE_STEP_FEE = 1350
VAT_MULTIPLIER = 1.1


def round_up_to_half_kg(weight_kg: float) -> float:
    """동백 요금이 0.5kg 단위로 끊어 청구되니, 실제 청구 무게 단위로 올림한다."""
    if weight_kg <= 0:
        return 0.0
    return math.ceil(weight_kg / 0.5) * 0.5

# (초과, 이하, 추가금액) - 해운 무게 할증
SEA_WEIGHT_SURCHARGE = [
    (4, 5, 500),
    (5, 10, 1000),
    (10, 15, 2400),
    (15, 20, 3000),
    (20, 25, 10000),
]

# (초과, 이하, 추가금액) - 부피(가로+세로+높이) 할증, 해운/항공 공통
GIRTH_SURCHARGE = [
    (80, 100, 500),
    (100, 120, 1000),
    (120, 140, 2400),
    (140, 160, 3000),
    (160, 190, 12000),
    (190, 230, 16000),
]

# (이상, 미만, 추가금액) - 항공 무게 할증
AIR_WEIGHT_SURCHARGE = [
    (2, 3, 500),
    (3, 4, 1000),
    (4, 5, 1500),
    (5, 6, 2000),
    (6, 7, 2500),
    (7, 8, 3000),
    (8, 9, 3500),
    (9, 10, 4000),
    (10, 11, 4500),
    (11, 12, 5000),
    (12, 13, 5500),
    (13, 14, 6000),
    (14, 15, 6500),
    (15, 19, 7000),
    (19, 21, 9000),
    (21, 23, 11000),
    (23, 25, 13000),
    (25, 27, 15000),
    (27, 29, 17000),
    (29, 31, 19000),
    (31, 33, 21000),
    (33, 35, 23000),
    (35, 40, 25000),
    (40, 45, 27000),
    (45, 50, 29000),
    (50, 55, 31000),
    (55, 60, 33000),
    (60, 65, 35000),
    (65, 70, 37000),
    (70, 75, 39000),
    (75, 80, 41000),
    (80, 85, 43000),
    (85, 90, 45000),
    (90, 95, 47000),
    (95, 100, 49000),
]

# 삼변합(가로+세로+높이) 기준 포장 할증
AIRCAP_SURCHARGE = [
    (0, 60, 1100),
    (60, 140, 2200),
    (140, 180, 3300),
    (180, 240, 5500),
    (240, 300, 7700),
    (300, float("inf"), 11000),
]

AIRBAR_SURCHARGE = [
    (0, 120, 4400),
    (120, 150, 8800),
    (150, 250, 13200),
    (250, 350, 17600),
    (350, float("inf"), 22000),
]

# 최장변 기준 우드포장 할증
WOOD_SURCHARGE = [
    (0, 120, 22000),
    (120, 140, 24000),
    (140, 160, 29000),
    (160, 180, 34000),
    (180, 200, 39000),
    (200, 220, 44000),
]

PACKAGING_TYPES = {
    "일반": None,
    "에어캡": AIRCAP_SURCHARGE,
    "에어막대기": AIRBAR_SURCHARGE,
    "우드포장": WOOD_SURCHARGE,
}


def base_fee(weight_kg: float, vat_included: bool = False) -> float:
    if weight_kg <= BASE_FIRST_STEP_KG:
        fee = BASE_FIRST_STEP_FEE
    elif weight_kg <= BASE_SECOND_STEP_KG:
        fee = BASE_SECOND_STEP_FEE
    else:
        steps = math.ceil((weight_kg - BASE_SECOND_STEP_KG) / BASE_STEP_KG)
        fee = BASE_SECOND_STEP_FEE + steps * BASE_STEP_FEE
    return round(fee * VAT_MULTIPLIER) if vat_included else fee


def _lookup_range(value, table, inclusive_low=False):
    for lo, hi, fee in table:
        if inclusive_low:
            if lo <= value < hi:
                return fee
        else:
            if lo < value <= hi:
                return fee
    return 0


def weight_surcharge(weight_kg: float, shipping_method: str = "해운") -> int:
    if shipping_method == "항공":
        return _lookup_range(weight_kg, AIR_WEIGHT_SURCHARGE, inclusive_low=True)
    return _lookup_range(weight_kg, SEA_WEIGHT_SURCHARGE, inclusive_low=False)


def girth_surcharge(girth_cm: float) -> int:
    if not girth_cm:
        return 0
    return _lookup_range(girth_cm, GIRTH_SURCHARGE, inclusive_low=False)


def packaging_surcharge(packaging_type: str, size_cm: float) -> int:
    table = PACKAGING_TYPES.get(packaging_type)
    if not table or not size_cm:
        return 0
    for lo, hi, fee in table:
        if lo < size_cm <= hi:
            return fee
    return 0


def calculate_shipping(
    weight_kg: float,
    girth_cm: float = None,
    shipping_method: str = "해운",
    packaging_type: str = "일반",
    vat_included: bool = False,
):
    """배송비 상세 내역을 dict로 반환한다."""
    base = base_fee(weight_kg, vat_included=vat_included)
    w_surcharge = weight_surcharge(weight_kg, shipping_method)
    g_surcharge = girth_surcharge(girth_cm) if girth_cm else 0
    p_surcharge = packaging_surcharge(packaging_type, girth_cm) if girth_cm else 0

    total = base + w_surcharge + g_surcharge + p_surcharge
    return {
        "기본요금": base,
        "무게할증": w_surcharge,
        "부피할증": g_surcharge,
        "포장할증": p_surcharge,
        "배송비합계": total,
    }
