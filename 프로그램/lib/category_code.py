"""픽투셀 양식에 내장된 쿠팡/스스 카테고리 코드 표에서 후보를 찾는다."""

import os

import openpyxl

TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pick2sell_template.xlsx"
)

SHEET_NAMES = {
    "쿠팡": "쿠팡 카테고리 코드",
    "스스": "스스 카테고리 코드",
}

_cache = {}


def load_categories(system: str = "쿠팡"):
    """system: '쿠팡' 또는 '스스'"""
    if system in _cache:
        return _cache[system]

    sheet_name = SHEET_NAMES[system]
    wb = openpyxl.load_workbook(TEMPLATE_PATH, data_only=True)
    ws = wb[sheet_name]
    categories = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        code, path = row[0], row[1]
        if code and path:
            categories.append((str(code), str(path)))
    _cache[system] = categories
    return categories


def find_candidates(keyword: str, system: str = "쿠팡", limit: int = 30):
    """카테고리 경로에 키워드 글자가 포함된 후보를 추려낸다 (단순 부분일치)."""
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    categories = load_categories(system)
    matches = [(code, path) for code, path in categories if keyword in path]
    return matches[:limit]
