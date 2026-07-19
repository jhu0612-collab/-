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
    """카테고리 경로에 키워드 글자가 포함된 후보를 추려낸다.

    먼저 키워드 전체로 찾아보고, 못 찾으면 "낚시구명조끼"처럼 합성어일 수 있으니
    2글자 이상 부분 문자열(긴 것부터)로 다시 찾는다.
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return []

    categories = load_categories(system)
    matches = [(code, path) for code, path in categories if keyword in path]
    if matches:
        return matches[:limit]

    n = len(keyword)
    substrings = []
    for length in range(min(n, 6), 1, -1):
        for i in range(n - length + 1):
            sub = keyword[i : i + length]
            if sub not in substrings:
                substrings.append(sub)

    seen_codes = set()
    combined = []
    for sub in substrings:
        for code, path in categories:
            if sub in path and code not in seen_codes:
                seen_codes.add(code)
                combined.append((code, path))
        if len(combined) >= limit:
            break
    return combined[:limit]


def top_level_groups(system: str = "쿠팡"):
    """카테고리 경로의 최상위 대분류만 중복없이 뽑는다."""
    categories = load_categories(system)
    groups = []
    for _, path in categories:
        top = path.split(">")[0]
        if top not in groups:
            groups.append(top)
    return groups


def candidates_in_group(group: str, system: str = "쿠팡", limit: int = 300):
    """특정 대분류(top_level_groups로 얻은 이름) 안에 속한 카테고리만 추려낸다."""
    categories = load_categories(system)
    return [(code, path) for code, path in categories if path == group or path.startswith(group + ">")][:limit]
