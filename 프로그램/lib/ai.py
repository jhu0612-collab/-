"""Claude API를 이용한 2차 카테고리/키워드 추천."""

import json

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


GROUP_PICK_PROMPT = """다음은 카테고리 대분류 목록이야:
{groups}

상품 키워드 "{keyword}"가 속할 것 같은 대분류를 하나만 골라줘.
목록에 있는 이름을 정확히 그대로 출력해. 설명이나 다른 텍스트는 붙이지 마.
"""


def guess_category_fallback(api_key: str, keyword: str, system: str):
    """단어/부분단어로 후보를 못 찾았을 때, 대분류부터 추정해서 그 안에서 가장 비슷한 코드를 고른다."""
    from lib import category_code

    groups = category_code.top_level_groups(system)
    if not groups:
        return None, "카테고리 대분류를 불러오지 못했어요."

    groups_text = "\n".join(groups)
    prompt = GROUP_PICK_PROMPT.format(groups=groups_text, keyword=keyword)
    group_answer, error = _call_claude(api_key, prompt, max_tokens=50)
    if error:
        return None, error

    picked_group = group_answer.strip()
    if picked_group not in groups:
        loose_matches = [g for g in groups if picked_group in g or g in picked_group]
        if not loose_matches:
            return None, f"AI가 고른 대분류('{picked_group}')를 목록에서 찾지 못했어요."
        picked_group = loose_matches[0]

    candidates = category_code.candidates_in_group(picked_group, system=system)
    if not candidates:
        return None, f"'{picked_group}' 대분류 안에서 후보를 찾지 못했어요."

    code, error = match_category_code(api_key, keyword, candidates)
    if error:
        return None, error
    return code, dict(candidates)[code]


WEIGHT_ESTIMATE_PROMPT = """다음은 타오바오/티몰에서 판매하는 상품명 리스트야.
각 상품의 실제 배송 무게(포장재 포함, 대략적인 배송 기준 무게)를 kg 단위로 상품 종류에 맞게 현실적으로 추정해줘.
예를 들어 게이밍 의자류는 5~10kg, 손톱깎이 세트 같은 작은 소품은 1kg 미만으로 추정하는 식으로, 상품 종류마다 다르게 판단해.

상품명 목록 (번호 순서대로):
{titles}

반드시 숫자만 담긴 JSON 배열로만 답해. 설명은 붙이지 말고, 상품 개수와 순서를 정확히 맞춰야 해.
예시 형식: [0.3, 6.5, 1.2]
"""


SEO_TITLE_PROMPT = """너는 한국 이커머스(쿠팡/스마트스토어) SEO 상품명 작성 전문가야.
아래 규칙을 반드시 지켜서, 타오바오/티몰 중국어 원본 상품명 목록을 각각 한국어 검색 키워드 나열형 상품명으로 바꿔줘.

[규칙]
1. 메인키워드는 반드시 상품명 맨 앞에 위치
2. 메인키워드는 반드시 붙여쓰기 (띄어쓰기 절대 없음)
3. 서브키워드는 4개를 기본으로 조합 (그 이상은 스팸 판정)
4. 전체 길이 50자는 반드시 지켜야 하는 최우선 규칙 — 메인키워드가 길어서 서브 4개를 넣으면
   50자를 넘는 경우엔 서브키워드를 3개, 그래도 넘으면 2개로 줄여서라도 50자를 넘기지 마.
   글자를 중간에서 잘라내지 말고, 항상 완전한 단어 단위로만 개수를 조절해.
5. 브랜드명 절대 포함 금지 (지재권 위험)
6. 각 상품명은 서로 다른 서브키워드 조합 (중복 금지)
7. 자연스러운 한국어 어순 (억지 조합 X)
8. 특수문자, 이모지, 괄호 사용 금지
9. 순수 검색 키워드만 나열 (문장 X)

메인키워드: {keyword}

[좋은 예시 - 메인키워드가 짧아서 서브 4개가 다 들어가는 경우]
메인: 낚시구명조끼
서브: 성인, 부력, 방수, 배낚시, 남성, 안전
출력:
["낚시구명조끼 성인 부력 방수 배낚시","낚시구명조끼 남성 안전 부력 조끼","낚시구명조끼 방수 성인 남성 안전"]

[나쁜 예시 - 절대 이렇게 하지 마세요]
- "낚시 구명 조끼 성인" (메인키워드 띄어쓰기)
- "성인 낚시구명조끼 부력" (메인키워드가 맨 앞 아님)
- "낚시구명조끼 Decathlon 성인 부력" (브랜드명 포함)
- "낚시구명조끼 성인 부력 방수 배낚시 남성 안전 조끼 프로" (서브 너무 많음, 4개 초과)
- 메인키워드 자체가 길어서 서브 4개를 다 넣으면 50자를 넘는데도 그대로 4개를 강행하는 것 (이 경우 서브를 3개, 2개로 줄여서 반드시 50자를 지켜야 함)
- "낚시구명조끼 [최고급] 성인용" (특수문자)

아래는 실제 변환해야 할 중국어 원본 상품명 목록이야 (번호 순서대로). 각 제목에 담긴 실제 특징(재질/색상/사이즈/용도 등)을 참고해서 서브키워드를 뽑아줘. 원문에 없는 특징은 지어내지 마.

{titles}

반드시 문자열만 담긴 JSON 배열로만 답해. 설명은 붙이지 말고, 상품 개수와 순서를 정확히 맞춰야 해.
"""


def generate_seo_titles(api_key: str, titles: list, keyword: str):
    """중국어 상품명 목록을 한국어 SEO 최적화 판매용 제목으로 일괄 변환한다."""
    if not titles:
        return None, "변환할 상품이 없어요."

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = SEO_TITLE_PROMPT.format(keyword=keyword, titles=numbered)
    text, error = _call_claude(api_key, prompt, max_tokens=2000)
    if error:
        return None, error

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        result = json.loads(text[start:end])
    except Exception as e:
        return None, f"AI 응답을 목록으로 해석하지 못했어요: {e}"

    if len(result) != len(titles):
        return None, f"AI가 반환한 제목 개수({len(result)})가 상품 개수({len(titles)})와 달라요. 다시 시도해보세요."

    return [str(t).strip()[:50] for t in result], None


def estimate_weights(api_key: str, titles: list):
    """titles 순서에 맞춰 무게(kg) 리스트를 추정해서 반환한다."""
    if not titles:
        return None, "추정할 상품이 없어요."

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = WEIGHT_ESTIMATE_PROMPT.format(titles=numbered)
    text, error = _call_claude(api_key, prompt, max_tokens=2000)
    if error:
        return None, error

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        weights = json.loads(text[start:end])
    except Exception as e:
        return None, f"AI 응답을 숫자 목록으로 해석하지 못했어요: {e}"

    if len(weights) != len(titles):
        return None, f"AI가 반환한 무게 개수({len(weights)})가 상품 개수({len(titles)})와 달라요. 다시 시도해보세요."

    try:
        weights = [float(w) for w in weights]
    except (TypeError, ValueError):
        return None, "AI 응답에 숫자가 아닌 값이 있어요."

    return weights, None
