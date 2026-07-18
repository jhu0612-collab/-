"""Claude API를 이용한 2차 카테고리/키워드 추천."""

import pandas as pd

RECOMMEND_PROMPT_TEMPLATE = """너는 해외구매대행 사업의 소싱 카테고리를 추천하는 전문가야.
아래는 셀러라이프 엑셀에서 1차 필터링(검색량 300~5,000, 해외배송비율 20%+, 해외배송 평균리뷰 1개+, 브랜드키워드 제외)을 통과한 후보 키워드 목록이야.

계절성, 트렌드성, 경쟁 리스크(대형 키워드인지), 구매대행 아이템으로서의 적합성을 종합적으로 고려해서
상위 {top_n}개 키워드를 추천하고, 각각 왜 추천하는지 1~2문장으로 이유를 설명해줘.
경쟁강도 수치는 함정일 수 있으니 참고만 하고 과신하지 마.

후보 목록 (검색량 높은 순):
{candidates}
"""


def _dataframe_to_text(df: pd.DataFrame, columns, max_rows=100) -> str:
    subset = df[columns].head(max_rows)
    lines = []
    for _, row in subset.iterrows():
        lines.append(" | ".join(f"{col}: {row[col]}" for col in columns))
    return "\n".join(lines)


def _extract_text(response) -> str:
    """응답 content 블록들 중 실제 텍스트 블록만 골라서 이어붙인다."""
    texts = []
    for block in getattr(response, "content", []) or []:
        block_text = getattr(block, "text", None)
        if block_text:
            texts.append(block_text)
    return "\n".join(texts)


def _call_claude(api_key: str, prompt: str, max_tokens: int = 2000):
    if not api_key:
        return None, "Anthropic API 키가 입력되지 않았어요. 사이드바에서 입력해주세요."

    try:
        import anthropic
    except ImportError:
        return None, "anthropic 패키지가 설치되지 않았어요. requirements.txt로 설치해주세요."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = _extract_text(response)
        if not text:
            return None, "AI가 빈 응답을 반환했어요. 다시 시도해보세요."
        return text, None
    except Exception as e:
        return None, f"AI 호출 실패: {type(e).__name__}: {e}"


def recommend_categories(api_key: str, df: pd.DataFrame, top_n: int = 10, max_candidates: int = 100):
    columns = [
        c
        for c in ["키워드", "카테고리", "최근1개월검색량", "계절성", "쿠팡해외배송비율", "쿠팡해외배송평균리뷰수"]
        if c in df.columns
    ]
    candidates_text = _dataframe_to_text(df, columns, max_rows=max_candidates)
    prompt = RECOMMEND_PROMPT_TEMPLATE.format(top_n=top_n, candidates=candidates_text)
    return _call_claude(api_key, prompt, max_tokens=2000)


CATEGORY_MATCH_PROMPT = """다음은 쿠팡 카테고리 코드 후보 목록이야 (코드: 카테고리경로 형식):
{candidates}

상품 키워드 "{keyword}"에 가장 적합한 카테고리 코드를 후보 중에서 하나만 골라줘.
답변은 반드시 코드 숫자만 출력해. 설명이나 다른 텍스트는 붙이지 마.
적합한 후보가 하나도 없으면 "없음"이라고만 답해.
"""


def match_category_code(api_key: str, keyword: str, candidates: list):
    """candidates: [(code, path), ...]"""
    if not candidates:
        return None, "후보 카테고리가 없어요."

    candidates_text = "\n".join(f"{code}: {path}" for code, path in candidates)
    prompt = CATEGORY_MATCH_PROMPT.format(candidates=candidates_text, keyword=keyword)
    text, error = _call_claude(api_key, prompt, max_tokens=50)
    if error:
        return None, error

    code = text.strip()
    valid_codes = {c for c, _ in candidates}
    if code not in valid_codes:
        return None, f"AI가 후보 중에 적합한 카테고리를 찾지 못했어요 (응답: {code})"
    return code, None
