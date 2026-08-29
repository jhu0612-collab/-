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


def _describe_content_blocks(response) -> str:
    """텍스트가 하나도 없을 때, content 블록들이 실제로 어떤 타입이었는지(예: thinking만
    있고 text는 하나도 없었는지) 진단용으로 요약한다."""
    blocks = getattr(response, "content", []) or []
    if not blocks:
        return "content 블록 0개"
    parts = []
    for block in blocks:
        block_type = getattr(block, "type", "?")
        thinking_text = getattr(block, "thinking", None)
        length = len(thinking_text) if thinking_text else 0
        parts.append(f"{block_type}({length}자)" if thinking_text else block_type)
    return ", ".join(parts)


def _call_claude(api_key: str, prompt: str, max_tokens: int = 2000):
    if not api_key:
        return None, "Anthropic API 키가 입력되지 않았어요. 사이드바에서 입력해주세요."

    try:
        import anthropic
    except ImportError:
        return None, "anthropic 패키지가 설치되지 않았어요. requirements.txt로 설치해주세요."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        # 상품 개수가 많으면 max_tokens이 커져서(예: 300*상품개수) SDK가 "10분 넘게 걸릴 것 같은
        # non-streaming 요청"으로 판단해 ValueError를 던지는 경우가 있다. 스트리밍으로 호출하면
        # 이 제한에 걸리지 않고, 응답이 도중에 끊겨도 타임아웃 보호를 받을 수 있다.
        with client.messages.stream(
            model="claude-sonnet-5",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()
        text = _extract_text(response)
        if not text:
            stop_reason = getattr(response, "stop_reason", None)
            usage = getattr(response, "usage", None)
            output_tokens = getattr(usage, "output_tokens", None) if usage else None
            blocks_desc = _describe_content_blocks(response)
            return None, (
                f"AI가 빈 응답을 반환했어요 (stop_reason: {stop_reason}, "
                f"output_tokens: {output_tokens}, content: {blocks_desc}). 다시 시도해보세요."
            )
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
    return _call_claude(api_key, prompt, max_tokens=max(4096, 300 * top_n))


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
    text, error = _call_claude(api_key, prompt, max_tokens=500)
    if error:
        return None, error

    valid_codes = {c for c, _ in candidates}
    code = text.strip()
    if code not in valid_codes:
        # 모델이 코드 앞뒤로 다른 설명을 덧붙였을 수 있으니, 응답 안에서 유효한
        # 후보 코드를 하나라도 찾을 수 있으면 그걸 쓴다.
        found = [c for c in valid_codes if c in text]
        code = found[0] if len(found) == 1 else None
    if not code or code not in valid_codes:
        return None, f"AI가 후보 중에 적합한 카테고리를 찾지 못했어요 (응답: {text.strip()[:200]})"
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
    group_answer, error = _call_claude(api_key, prompt, max_tokens=500)
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

각 상품마다 번호(n)와 추정무게(kg)를 짝지어서 JSON 배열로만 답해. 설명은 붙이지 마.
목록에 있는 번호를 하나도 빠짐없이, 위에 나온 번호 그대로 포함해야 해.
예시 형식: [{{"n": 1, "kg": 0.3}}, {{"n": 2, "kg": 6.5}}]
"""


def _parse_weight_response(text: str) -> dict:
    """AI 응답 JSON 배열을 {{번호: 무게}} 형태로 파싱한다.

    번호를 같이 받는 이유는, 상품 개수가 많을 때(70~100개+) AI가 배열 중간에서
    항목 한두 개를 누락시키는 경우가 있는데, 이때 번호가 없으면 그냥 순서가
    밀려버려서 전혀 엉뚱한 상품에 엉뚱한 무게가 매칭돼버린다. 번호를 같이 받으면
    어떤 상품이 빠졌는지 정확히 알아내서 그 부분만 다시 물어볼 수 있다.
    """
    start = text.index("[")
    end = text.rindex("]") + 1
    data = json.loads(text[start:end])

    result = {}
    for entry in data:
        if isinstance(entry, dict):
            n, kg = entry.get("n"), entry.get("kg")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            n, kg = entry
        else:
            continue
        try:
            result[int(n)] = float(kg)
        except (TypeError, ValueError):
            continue
    return result


SEO_TITLE_PROMPT = """너는 한국 이커머스(쿠팡/스마트스토어/11번가 ESM) SEO 상품명 작성 전문가야.
아래 규칙을 반드시 지켜서, 타오바오/티몰 중국어 원본 상품명 목록을 각각 한국어 검색 키워드 나열형 상품명으로 바꿔줘.
상품명은 띄어쓰기 포함 최대 {limit}자까지 쓸 수 있어. 짧게 쓰지 말고, 실제 특징을 최대한 채워서 {limit}자에 가깝게(최소 {min_fill_ratio_pct}% 이상) 만들어야 해 — 27자, 30자처럼 여유를 남겨두고 짧게 끝내는 건 이 규칙 위반이야.

[규칙]
1. 메인키워드("{keyword}")는 절대 변형하지 말고 정확히 그 형태 그대로 상품명의
   맨 앞에 써. 메인키워드가 "철근 결속기"처럼 공백을 포함한 두 단어 이상이어도,
   그 전체를 하나로 취급해서 통째로 맨 앞에 그대로 두고 절대 단어 순서를 바꾸거나
   중간에 다른 단어를 끼워넣지 마 (예: "자동 철근 결속기"나 "철근 바인딩기"처럼
   단어를 재배열하거나 다른 단어로 바꾸는 것 금지). 메인키워드 앞에 다른 수식어를
   붙이는 것도 금지("특대형봉제인형"처럼 메인키워드 앞에 뭔가 끼워넣는 것 금지).
2. 메인키워드 다음에는 반드시 띄어쓰기 하나를 넣고, 그 뒤에 서브키워드를 각각
   별도의 띄어쓰기로 구분된 단어로 나열해. 서브키워드를 메인키워드 뒤에 바로
   붙여서 새 복합명사를 만들지 마 (예: "봉제인형베개"처럼 붙이면 안 되고
   "봉제인형 베개"처럼 반드시 띄어써야 함).
3. 서브키워드는 4개를 기본으로 반드시 채우고, {limit}자에 여유가 남으면 5개, 6개까지
   더 채워서 최대한 길게 만들어야 해 (서브 없이 메인키워드만 있는 "봉제인형" 같은
   출력은 금지). {limit}자를 넘길 때만 개수를 줄이되, 그 경우에도 절대 3개 밑으로는
   줄이지 마. 서브키워드가 7개를 넘는 것도 스팸 판정이라 금지.
4. 전체 길이 {limit}자는 반드시 지켜야 하는 최우선 규칙 — 절대 넘기지 마. 동시에
   위에서 말한 최소 채움 비율({min_fill_ratio_pct}%)도 지켜야 해. 글자를 중간에서
   잘라내지 말고, 항상 완전한 단어 단위로만 개수를 조절해.
5. 브랜드명 절대 포함 금지 (지재권 위험)
6. 각 상품명은 서로 다른 서브키워드 조합 (중복 금지) — 출력하기 전에 배열 안에 완전히
   똑같은 문자열이 두 개 이상 있는지 반드시 스스로 검토하고, 있으면 다른 조합으로 바꿔.
   상품 개수가 많아서 서브키워드 조합이 겹칠 것 같으면, 순서를 바꾸거나 다른 속성을
   골라서라도 전부 서로 달라야 해.
7. 자연스러운 한국어 어순 (억지 조합 X)
8. 특수문자, 이모지, 괄호 사용 금지
9. 순수 검색 키워드만 나열 (문장 X)

메인키워드: {keyword}
{related_keywords_section}
[좋은 예시 - {limit}자에 가깝게 최대한 채운 경우]
메인: 낚시구명조끼
서브: 성인, 부력, 방수, 배낚시, 남성, 안전
출력:
["낚시구명조끼 성인 부력 방수 배낚시 안전","낚시구명조끼 남성 안전 부력 조끼 배낚시","낚시구명조끼 방수 성인 남성 안전 조끼"]

[좋은 예시 - 메인키워드가 공백 포함 두 단어("철근 결속기")인 경우]
메인: 철근 결속기
서브: 충전식, 리튬배터리, 자동, 전동공구, 건설용
출력:
["철근 결속기 충전식 리튬배터리 자동 전동공구","철근 결속기 건설용 자동 충전식 전동공구"]
(메인키워드 "철근 결속기"는 통째로 그대로, 항상 맨 앞. "자동 철근 결속기"나 "철근 바인딩기"처럼
단어를 앞으로 옮기거나 다른 말로 바꾸면 절대 안 됨)

[나쁜 예시 - 절대 이렇게 하지 마세요]
- "낚시 구명 조끼 성인" (메인키워드 띄어쓰기)
- "성인 낚시구명조끼 부력" (메인키워드가 맨 앞 아님)
- "자동 철근 결속기 충전식" (메인키워드가 "철근 결속기"인데 "자동"이 앞에 끼어들어서
  메인키워드가 통째로 맨 앞에 오지 못함)
- "철근 바인딩기 자동 충전식" (메인키워드 "철근 결속기"를 "철근 바인딩기"로 바꿔버림 -
  같은 뜻이어도 다른 단어로 바꾸면 절대 안 되고 정확히 주어진 그대로 써야 함)
- "특대형봉제인형 방수 소재" (메인키워드 앞에 수식어가 붙어버림 - 메인키워드는 "봉제인형"인데
  "특대형"이 앞에 끼어들어감. "봉제인형 특대형 방수 소재"처럼 메인키워드 뒤에 와야 함)
- "봉제인형베개 특대형 소재 선물" (서브키워드 "베개"가 메인키워드에 바로 붙어서 새로운
  복합명사가 되어버림. "봉제인형 베개 특대형 소재"처럼 띄어써야 함)
- "봉제인형" (서브키워드가 하나도 없이 메인키워드만 있음)
- "낚시구명조끼 성인" (27자 정도밖에 안 채움 - {limit}자 중 한참 못 미치게 짧게
  끝내버림. 실제 특징을 더 찾아서 서브키워드를 늘려야 함)
- "낚시구명조끼 Decathlon 성인 부력" (브랜드명 포함)
- "낚시구명조끼 성인 부력 방수 배낚시 남성 안전 조끼 통기성" (서브 너무 많음, 7개 초과)
- 메인키워드 자체가 길어서 서브 4개를 다 넣으면 {limit}자를 넘는데도 그대로 강행하는 것 (이 경우 서브를 3개로 줄여서 반드시 {limit}자를 지켜야 함)
- "낚시구명조끼 [최고급] 성인용" (특수문자)

아래는 실제 변환해야 할 중국어 원본 상품명 목록이야 (번호 순서대로). 각 제목에 담긴 실제 특징(재질/색상/사이즈/용도 등)을 참고해서 서브키워드를 뽑아줘. 일부 항목엔 괄호로 "(참고 상세속성: ...)"이 붙어있는데, 이건 상품 상세페이지에서 가져온 실제 스펙 정보라 제목보다 신뢰도가 높으니 적극 참고해줘. 원문/상세속성에 없는 특징은 지어내지 마.

{titles}

반드시 문자열만 담긴 JSON 배열로만 답해. 설명은 붙이지 말고, 상품 개수와 순서를 정확히 맞춰야 해.
"""

TITLE_MAX_LENGTH = 50
TITLE_MIN_FILL_RATIO = 0.8
SEO_TITLE_CHUNK_SIZE = 25


def _build_related_keywords_section(related_keywords: list) -> str:
    """네이버 검색광고 연관키워드(검색량 높은 순)를 프롬프트에 끼워 넣을 문단으로 만든다.

    related_keywords가 없으면 빈 문자열을 반환해서 프롬프트에 아무 영향도 주지 않는다."""
    if not related_keywords:
        return ""
    joined = ", ".join(related_keywords)
    return (
        "\n[참고: 이 상품군에서 실제 검색량이 높은 연관 키워드 (네이버 검색광고 데이터, 검색량 높은 순)]\n"
        f"{joined}\n"
        "위 연관 키워드 중 각 상품의 실제 특징과 맞아떨어지는 게 있으면 서브키워드로 최우선 활용해줘 "
        "(실제로 많이 검색되는 단어라 노출에 유리해). 상품과 안 맞는 연관 키워드를 억지로 끼워넣지는 마.\n"
    )


def _generate_seo_titles_chunk(
    api_key: str, titles: list, keyword: str, attribute_contexts: list = None, related_keywords: list = None
):
    """titles 한 청크(최대 SEO_TITLE_CHUNK_SIZE개)에 대해 SEO 제목을 한 번에 생성한다."""
    lines = []
    for i, t in enumerate(titles):
        line = f"{i + 1}. {t}"
        if attribute_contexts and i < len(attribute_contexts) and attribute_contexts[i]:
            line += f" (참고 상세속성: {attribute_contexts[i]})"
        lines.append(line)
    numbered = "\n".join(lines)
    prompt = SEO_TITLE_PROMPT.format(
        keyword=keyword,
        titles=numbered,
        limit=TITLE_MAX_LENGTH,
        min_fill_ratio_pct=int(TITLE_MIN_FILL_RATIO * 100),
        related_keywords_section=_build_related_keywords_section(related_keywords),
    )
    # 25개(7500토큰)로 청크를 나눠도 output_tokens가 정확히 그 한도까지 차면서 텍스트가
    # 하나도 안 나온 사례가 실제로 있었다 - 이 프롬프트의 규칙이 많아서 눈에 안 보이는
    # 처리에 토큰을 많이 쓰는 것으로 보여서, 상품 개수 대비 훨씬 넉넉하게 잡는다.
    max_tokens = max(8192, 1500 * len(titles))
    text, error = _call_claude(api_key, prompt, max_tokens=max_tokens)
    if error:
        return None, error

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        result = json.loads(text[start:end])
    except Exception as e:
        return None, f"AI 응답을 목록으로 해석하지 못했어요 (응답이 도중에 잘렸을 수 있어요): {e}"

    if len(result) != len(titles):
        return None, f"AI가 반환한 제목 개수({len(result)})가 상품 개수({len(titles)})와 달라요. 다시 시도해보세요."

    return [str(t).strip()[:TITLE_MAX_LENGTH] for t in result], None


def _generate_seo_titles_resilient(
    api_key: str, titles: list, keyword: str, attribute_contexts: list, related_keywords: list = None, attempts: int = 2
):
    """청크 생성을 시도하고, 반복 실패하면 절반으로 쪼개서 각각 다시 시도한다.

    끝까지(개별 상품 하나 단위까지) 쪼개서라도 최대한 다 채우는 게 목표라, 어느 크기에서
    막히든 결국 더 작은 단위로 내려가면서 계속 재시도한다. 상품 100~300개 정도의 배치를
    통째로 실패 처리하지 않고 끝까지 살려내기 위한 안전망이다."""
    for _ in range(attempts):
        names, error = _generate_seo_titles_chunk(api_key, titles, keyword, attribute_contexts, related_keywords)
        if not error:
            return names, None

    if len(titles) <= 1:
        return [""] * len(titles), error

    mid = len(titles) // 2
    left_contexts = attribute_contexts[:mid] if attribute_contexts else None
    right_contexts = attribute_contexts[mid:] if attribute_contexts else None
    left_names, left_error = _generate_seo_titles_resilient(
        api_key, titles[:mid], keyword, left_contexts, related_keywords, attempts
    )
    right_names, right_error = _generate_seo_titles_resilient(
        api_key, titles[mid:], keyword, right_contexts, related_keywords, attempts
    )
    return left_names + right_names, left_error or right_error


def generate_seo_titles(api_key: str, titles: list, keyword: str, attribute_contexts: list = None, related_keywords: list = None):
    """중국어 상품명 목록을 한국어 SEO 최적화 판매용 제목으로 일괄 변환한다.

    attribute_contexts: titles와 같은 순서/길이의 문자열 리스트(enrichWithDetails로 받은
    상세속성 요약). 있으면 제목만으로는 안 보이는 재질/기능 정보까지 참고해서 서브키워드를 뽑는다.

    related_keywords: 네이버 검색광고 연관키워드 조회로 얻은, 이 메인키워드와 관련해서 실제
    검색량이 높은 키워드 문자열 리스트(검색량 높은 순). 있으면 서브키워드를 고를 때 감이 아니라
    실제 검색 데이터를 우선 참고하게 만들어서 노출에 유리한 제목을 만든다.

    상품이 많으면(예: 100개) max_tokens도 같이 커지는데, 응답이 그 한도에 정확히 맞춰
    끊기면(stop_reason=max_tokens) 스트리밍 응답 조립 중 텍스트가 통째로 비어버리는
    경우가 실제로 있었다. 그래서 한 번에 다 보내지 않고 SEO_TITLE_CHUNK_SIZE개씩
    나눠서 여러 번 호출하고, 그래도 실패하는 청크는 계속 절반씩 쪼개가며 재시도해서
    (_generate_seo_titles_resilient) 상품 개수가 몇 백 개가 되어도 최대한 전부 채운다.
    """
    if not titles:
        return None, "변환할 상품이 없어요."

    all_names = [""] * len(titles)
    for start in range(0, len(titles), SEO_TITLE_CHUNK_SIZE):
        chunk_titles = titles[start : start + SEO_TITLE_CHUNK_SIZE]
        chunk_contexts = (
            attribute_contexts[start : start + SEO_TITLE_CHUNK_SIZE] if attribute_contexts else None
        )
        chunk_names, _ = _generate_seo_titles_resilient(
            api_key, chunk_titles, keyword, chunk_contexts, related_keywords
        )
        all_names[start : start + len(chunk_titles)] = chunk_names

    # _fix_bad_titles는 형식 오류/중복뿐 아니라, 위에서 빈 칸("")으로 남은 청크도
    # (원본 제목을 그대로 다시 넘겨서) 한 번 더 채워보려고 시도한다 - 다른 프롬프트로
    # 다시 시도하는 것이라 여기서 살아날 수도 있다.
    all_names = _fix_bad_titles(api_key, all_names, titles, keyword)

    still_blank = [i + 1 for i, n in enumerate(all_names) if not n]
    if still_blank:
        succeeded = len(titles) - len(still_blank)
        examples = ", ".join(str(n) for n in still_blank[:10]) + "번"
        if len(still_blank) > 10:
            examples += " 등"
        warning = (
            f"{succeeded}/{len(titles)}개는 생성했지만, {len(still_blank)}개 상품({examples})은 "
            "재시도까지 실패해서 빈 칸으로 남겨뒀어요. 표에서 빈 칸인 상품만 직접 입력하거나, 다시 생성 버튼을 눌러보세요."
        )
        return all_names, warning

    return all_names, None


FIX_SEO_TITLE_PROMPT = """방금 아래 상품들의 한국어 판매용 제목을 만들었는데, 문제가 있는 것들이 있어서
다시 만들어야 해 (형식이 틀렸거나, 다른 상품과 완전히 똑같은 이름이 나왔거나).

[규칙]
1. 메인키워드("{keyword}")를 절대 변형하지 말고 정확히 그 형태 그대로 맨 앞에 써.
   메인키워드가 "철근 결속기"처럼 공백 포함 두 단어 이상이어도 통째로 하나로 취급해서
   그대로 맨 앞에 두고, 단어 순서를 바꾸거나 다른 단어로 바꾸거나 중간에 다른 말을
   끼워넣지 마 (예: "자동 철근 결속기"나 "철근 바인딩기"로 바꾸는 것 금지).
   메인키워드 앞에 다른 단어를 붙이는 것도 금지("특대형봉제인형"처럼 앞에 끼워넣는 것 금지).
2. 메인키워드 다음에 반드시 띄어쓰기 하나, 그 뒤에 서브키워드를 각각 띄어쓰기로 구분된
   별도 단어로 나열해. 서브키워드를 메인키워드에 바로 붙여서 새 복합명사를 만들지 마
   (예: "봉제인형베개"가 아니라 "봉제인형 베개").
3. 서브키워드는 4개를 기본으로 반드시 채우고, {limit}자에 여유가 남으면 5개, 6개까지
   더 채워서 최대한 길게 만들어야 해 (0개는 금지). 전체 길이는 {limit}자를 넘기면 안 되고,
   동시에 최소 {min_fill_ratio_pct}% 이상은 채워야 해서 너무 짧게 끝내면 안 돼. {limit}자를
   넘길 때만 개수를 줄이되 3개 밑으로는 줄이지 마.
4. 브랜드명/특수문자/이모지/괄호 절대 금지, 순수 키워드 나열형 (문장 X)
5. 아래 "이미 사용 중인 이름"과도 절대 겹치면 안 되고, 새로 만드는 것들끼리도 서로 달라야 해

메인키워드: {keyword}

이미 사용 중인 이름 (겹치면 안 됨):
{used_titles}

새로 이름 지어야 할 상품 원문 (번호 순서대로):
{titles}

반드시 문자열만 담긴 JSON 배열로만 답해. 설명 붙이지 말고 개수와 순서를 정확히 맞춰야 해.
"""


def _is_malformed_seo_title(name: str, keyword: str) -> bool:
    """형식 오류(메인키워드가 맨 앞에 그대로 없음/서브키워드 없음)이거나, 글자수를
    최소 채움 비율(TITLE_MIN_FILL_RATIO)만큼도 못 채운 경우 재생성 대상으로 본다.

    메인키워드가 "철근 결속기"처럼 공백을 포함한 여러 단어일 수 있어서, 예전엔
    name.split()[0](제목의 첫 단어 하나)와 keyword 전체를 비교했는데, 이러면
    keyword가 두 단어 이상인 경우 항상 다르다고 나와서 정상 제목까지 전부
    오탐(형식 오류로 판정)됐다. 대신 제목이 keyword로 "시작하는지"와, keyword
    바로 뒤가 새 단어 경계(공백 또는 끝)인지를 확인한다.

    단, 메인키워드 자체가 이미 최소 채움 기준을 넘길 만큼 길면(그래서 서브키워드를
    더 넣을 여지가 별로 없으면) 짧다고 재생성시키지 않는다.
    """
    if not name.startswith(keyword):
        return True
    rest = name[len(keyword):]
    if rest and not rest.startswith(" "):
        return True  # 메인키워드 뒤에 서브키워드가 바로 붙어서 새 복합명사가 됨
    if not rest.strip():
        return True  # 서브키워드가 하나도 없음
    min_fill_length = TITLE_MAX_LENGTH * TITLE_MIN_FILL_RATIO
    if len(name) < min_fill_length and len(keyword) < min_fill_length:
        return True
    return False


def _fix_bad_titles(api_key: str, names: list, original_titles: list, keyword: str, max_rounds: int = 2):
    """생성된 이름 중 형식이 틀렸거나(메인키워드가 맨 앞이 아님/붙어버림/서브키워드 없음)
    완전히 똑같은 이름이 있으면, 그 부분만 다시 생성한다.

    재생성이 실패하거나 여전히 문제가 있으면 원래 결과를 그대로 둔다 (전체 실패시키지 않음).
    """
    for _ in range(max_rounds):
        seen = set()
        bad_indices = []
        for i, name in enumerate(names):
            if _is_malformed_seo_title(name, keyword) or name in seen:
                bad_indices.append(i)
            else:
                seen.add(name)
        if not bad_indices:
            break

        # bad_indices가 많을 때(예: 실패한 청크 전체가 빈 칸으로 넘어온 경우) 한 번에 다
        # 보내면 또 같은 문제(큰 배치 -> 빈 응답)가 재현될 수 있어서, 이것도 청크로 나눈다.
        for chunk_start in range(0, len(bad_indices), SEO_TITLE_CHUNK_SIZE):
            chunk_bad_indices = bad_indices[chunk_start : chunk_start + SEO_TITLE_CHUNK_SIZE]
            used_titles = "\n".join(sorted(seen)) if seen else "(없음)"
            numbered = "\n".join(f"{n + 1}. {original_titles[i]}" for n, i in enumerate(chunk_bad_indices))
            prompt = FIX_SEO_TITLE_PROMPT.format(
                keyword=keyword,
                used_titles=used_titles,
                titles=numbered,
                limit=TITLE_MAX_LENGTH,
                min_fill_ratio_pct=int(TITLE_MIN_FILL_RATIO * 100),
            )
            max_tokens = max(8192, 1500 * len(chunk_bad_indices))
            text, error = _call_claude(api_key, prompt, max_tokens=max_tokens)
            if error:
                continue  # 이 청크만 실패, 다른 청크는 계속 시도한다
            try:
                start = text.index("[")
                end = text.rindex("]") + 1
                new_names = json.loads(text[start:end])
            except Exception:
                continue
            if len(new_names) != len(chunk_bad_indices):
                continue
            for idx, new_name in zip(chunk_bad_indices, new_names):
                fixed = str(new_name).strip()[:TITLE_MAX_LENGTH]
                names[idx] = fixed
                seen.add(fixed)  # 같은 라운드의 다음 청크가 중복을 피할 수 있게 즉시 반영
    return names


_WEIGHT_CHUNK_SIZE = 25


def _estimate_weights_chunk(api_key: str, titles: list):
    """titles 한 청크에 대해 무게를 한 번에 추정한다 (번호 누락분은 한 번 더 물어봄)."""
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = WEIGHT_ESTIMATE_PROMPT.format(titles=numbered)
    # 25개(예전 300토큰/개)로 청크를 나눠도 SEO 제목 생성 때와 같은 이유로 빈 응답이 날 수
    # 있어서, 상품당 토큰을 훨씬 넉넉하게 잡는다.
    max_tokens = max(8192, 1200 * len(titles))
    text, error = _call_claude(api_key, prompt, max_tokens=max_tokens)
    if error:
        return None, error

    try:
        weight_by_n = _parse_weight_response(text)
    except Exception as e:
        return None, f"AI 응답을 숫자 목록으로 해석하지 못했어요 (응답이 도중에 잘렸을 수 있어요): {e}"

    missing = [i + 1 for i in range(len(titles)) if (i + 1) not in weight_by_n]
    if missing:
        retry_numbered = "\n".join(f"{n}. {titles[n - 1]}" for n in missing)
        retry_prompt = WEIGHT_ESTIMATE_PROMPT.format(titles=retry_numbered)
        retry_text, retry_error = _call_claude(api_key, retry_prompt, max_tokens=max(2048, 1200 * len(missing)))
        if not retry_error:
            try:
                weight_by_n.update(_parse_weight_response(retry_text))
            except Exception:
                pass

    still_missing = [i + 1 for i in range(len(titles)) if (i + 1) not in weight_by_n]
    if still_missing:
        shown = still_missing[:10]
        more = f" 외 {len(still_missing) - 10}개" if len(still_missing) > 10 else ""
        return None, f"AI가 일부 상품(번호: {shown}{more})의 무게를 추정하지 못했어요."

    return [weight_by_n[i + 1] for i in range(len(titles))], None


def _estimate_weights_resilient(api_key: str, titles: list, attempts: int = 2):
    """청크가 계속 실패하면 절반씩 쪼개서 재시도한다 (SEO 제목 생성과 같은 전략)."""
    for _ in range(attempts):
        weights, error = _estimate_weights_chunk(api_key, titles)
        if not error:
            return weights
    if len(titles) <= 1:
        return [None] * len(titles)
    mid = len(titles) // 2
    return (
        _estimate_weights_resilient(api_key, titles[:mid], attempts)
        + _estimate_weights_resilient(api_key, titles[mid:], attempts)
    )


def estimate_weights(api_key: str, titles: list):
    """titles 순서에 맞춰 무게(kg) 리스트를 추정해서 반환한다.

    상품이 많으면(예: 100개) 한 번에 보내지 않고 _WEIGHT_CHUNK_SIZE개씩 나눠서 여러 번
    호출하고, 실패한 청크는 계속 절반으로 쪼개가며 재시도한다 - generate_seo_titles와
    같은 이유(큰 배치일수록 max_tokens을 정확히 소진하며 빈 응답이 나는 문제)로,
    상품 개수가 몇 백 개가 되어도 최대한 전부 채운다.
    """
    if not titles:
        return None, "추정할 상품이 없어요."

    all_weights = []
    for start in range(0, len(titles), _WEIGHT_CHUNK_SIZE):
        chunk = titles[start : start + _WEIGHT_CHUNK_SIZE]
        all_weights.extend(_estimate_weights_resilient(api_key, chunk))

    still_missing = [i + 1 for i, w in enumerate(all_weights) if w is None]
    if still_missing:
        shown = still_missing[:10]
        more = f" 외 {len(still_missing) - 10}개" if len(still_missing) > 10 else ""
        return None, f"AI가 일부 상품(번호: {shown}{more})의 무게를 재시도까지 추정하지 못했어요. 다시 시도해보세요."

    return all_weights, None


RELEVANCE_CHECK_PROMPT = """다음은 "{keyword}" 키워드로 검색해서 나온 타오바오/티몰 상품명 목록이야.
각 상품이 실제로 "{keyword}" 카테고리에 해당하는 상품인지 판단해줘.

[판단 기준]
- 검색어와 완전히 다른 종류의 물건이면(예: "낚시구명조끼"를 검색했는데 낚시와 무관한 일반
  방한조끼/등산조끼가 섞여있는 경우) 부적합(false)으로 판단해.
- 제목에 검색어와 겹치는 단어(한자/음차 포함)가 하나 들어있다고 무조건 적합으로 판단하지 마.
  중국어 원제목 특성상 단어가 겹쳐도 실제 상품 종류(완제품 vs 부속품/부품, 다른 용도)가 다르면
  부적합으로 판단해야 해. 예: "{keyword}"가 자동차 발매트인데, 실제로는 클러치 페달
  리미터/브레이크 라이트 센서/개스킷/클립 같은 자동차 부품 조립세트이고 제목에 우연히
  "脚垫(발매트/발판)" 같은 단어가 섞여있을 뿐인 경우 - 이건 부적합(false)이야.
- 판매자가 과장/비유적 마케팅 문구로 검색어 단어를 실제로 제목에 써놓은 경우도 속지 마.
  예: "{keyword}"가 캠핑냉장고인데, 실제로는 냉각 기능이 전혀 없는 칸막이형 과일/식품
  보관용기(도시락통)인데 제목에 "이동식 냉장고"라고 비유적으로 써놓은 경우 - 진짜
  냉각 기능(전기냉각/보냉재 내장 등)이 있는지 실제 상품 설명·상세속성으로 확인하고,
  없으면 부적합(false)으로 판단해.
- 참고 상세속성이 붙어있으면(적용차종/재질/유형/기능 등 실제 스펙 정보) 제목보다 그걸 최우선으로
  참고해서 판단해 - 제목만 봐서 헷갈려도 상세속성을 보면 실제 상품 종류가 명확해지는 경우가 많아.
- 검색어의 하위 종류, 디자인 변형, 세부 스펙 차이 정도는 다 적합(true)으로 판단해.
- 애매하거나 확신이 안 서면 무조건 적합(true)으로 판단해 (정상 상품을 잘못 걸러내는 것보다,
  애매한 걸 놓치는 게 나아). 다만 위에서 말한 "단어만 겹치는 경우"나 "과장 마케팅 문구로
  검색어를 써놓았지만 실제 핵심 기능이 없는 경우"는 애매한 게 아니라 명확한 부적합이니
  헷갈리지 마.

상품명 목록 (번호 순서대로, 일부는 괄호로 참고 상세속성이 붙어있어):
{titles}

각 상품마다 번호(n)와 적합여부(rel, true/false)를 짝지어서 JSON 배열로만 답해. 설명은 붙이지 마.
목록에 있는 번호를 하나도 빠짐없이, 위에 나온 번호 그대로 포함해야 해.
예시 형식: [{{"n": 1, "rel": true}}, {{"n": 2, "rel": false}}]
"""


def _parse_relevance_response(text: str) -> dict:
    """AI 응답 JSON 배열을 {번호: 적합여부(bool)} 형태로 파싱한다."""
    start = text.index("[")
    end = text.rindex("]") + 1
    data = json.loads(text[start:end])

    result = {}
    for entry in data:
        if isinstance(entry, dict):
            n, rel = entry.get("n"), entry.get("rel")
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            n, rel = entry
        else:
            continue
        try:
            result[int(n)] = bool(rel)
        except (TypeError, ValueError):
            continue
    return result


_RELEVANCE_CHUNK_SIZE = 25


def _check_relevance_chunk(api_key: str, titles: list, keyword: str, attribute_contexts: list = None):
    lines = []
    for i, t in enumerate(titles):
        line = f"{i + 1}. {t}"
        if attribute_contexts and i < len(attribute_contexts) and attribute_contexts[i]:
            line += f" (참고 상세속성: {attribute_contexts[i]})"
        lines.append(line)
    numbered = "\n".join(lines)
    prompt = RELEVANCE_CHECK_PROMPT.format(keyword=keyword, titles=numbered)
    max_tokens = max(8192, 600 * len(titles))
    text, error = _call_claude(api_key, prompt, max_tokens=max_tokens)
    if error:
        return None, error

    try:
        rel_by_n = _parse_relevance_response(text)
    except Exception as e:
        return None, f"AI 응답을 해석하지 못했어요 (응답이 도중에 잘렸을 수 있어요): {e}"

    missing = [i + 1 for i in range(len(titles)) if (i + 1) not in rel_by_n]
    if missing:
        retry_lines = []
        for n in missing:
            line = f"{n}. {titles[n - 1]}"
            if attribute_contexts and (n - 1) < len(attribute_contexts) and attribute_contexts[n - 1]:
                line += f" (참고 상세속성: {attribute_contexts[n - 1]})"
            retry_lines.append(line)
        retry_prompt = RELEVANCE_CHECK_PROMPT.format(keyword=keyword, titles="\n".join(retry_lines))
        retry_text, retry_error = _call_claude(api_key, retry_prompt, max_tokens=max(2048, 600 * len(missing)))
        if not retry_error:
            try:
                rel_by_n.update(_parse_relevance_response(retry_text))
            except Exception:
                pass

    if len(rel_by_n) != len(titles):
        return None, "일부 상품의 적합여부를 판단하지 못했어요."

    return [rel_by_n[i + 1] for i in range(len(titles))], None


def _check_relevance_resilient(api_key: str, titles: list, keyword: str, attribute_contexts: list = None, attempts: int = 2):
    for _ in range(attempts):
        rel, error = _check_relevance_chunk(api_key, titles, keyword, attribute_contexts)
        if not error:
            return rel
    if len(titles) <= 1:
        return [None] * len(titles)
    mid = len(titles) // 2
    left_contexts = attribute_contexts[:mid] if attribute_contexts else None
    right_contexts = attribute_contexts[mid:] if attribute_contexts else None
    return (
        _check_relevance_resilient(api_key, titles[:mid], keyword, left_contexts, attempts)
        + _check_relevance_resilient(api_key, titles[mid:], keyword, right_contexts, attempts)
    )


def check_relevance(api_key: str, titles: list, keyword: str, attribute_contexts: list = None):
    """titles 순서에 맞춰 검색 키워드와 실제로 맞는 상품인지(True/False) 리스트를 반환한다.

    타오바오 검색결과엔 이따금 검색어와 무관한 상품이 섞여 들어오는데(예: 낚시구명조끼
    검색인데 일반 조끼가 섞임, 또는 자동차 발매트를 검색했는데 제목에 "脚垫" 단어만
    겹치는 자동차 부품 클립/개스킷 조립세트가 섞임), 제목만 봐서는 코드로 걸러내기
    어려워서 AI로 판단한다.

    attribute_contexts: titles와 같은 순서/길이의 문자열 리스트(enrichWithDetails로 받은
    상세속성 요약). 있으면 제목만으로는 헷갈리는 경우에도 실제 스펙으로 정확히 판단한다.

    상품이 많으면 _RELEVANCE_CHUNK_SIZE개씩 나눠서 호출하고, 실패한 청크는 절반씩
    쪼개가며 재시도한다(generate_seo_titles/estimate_weights와 같은 전략). 재시도까지
    끝내 실패한 상품은 안전하게 적합(true)으로 간주해서, 오탐으로 정상 상품이 통째로
    빠지는 것보단 낫게 처리한다.
    """
    if not titles:
        return None, "확인할 상품이 없어요."

    all_rel = []
    for start in range(0, len(titles), _RELEVANCE_CHUNK_SIZE):
        chunk = titles[start : start + _RELEVANCE_CHUNK_SIZE]
        chunk_contexts = (
            attribute_contexts[start : start + _RELEVANCE_CHUNK_SIZE] if attribute_contexts else None
        )
        all_rel.extend(_check_relevance_resilient(api_key, chunk, keyword, chunk_contexts))

    return [True if r is None else r for r in all_rel], None
