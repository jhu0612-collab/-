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


SEO_TITLE_PROMPT = """너는 한국 이커머스(쿠팡/스마트스토어) SEO 상품명 작성 전문가야.
아래 규칙을 반드시 지켜서, 타오바오/티몰 중국어 원본 상품명 목록을 각각 한국어 검색 키워드 나열형 상품명으로 바꿔줘.

[규칙]
1. 메인키워드("{keyword}")는 절대 변형하지 말고 정확히 그 형태 그대로 상품명의
   맨 앞 단어로 써. 메인키워드 앞에 다른 수식어를 붙이거나("특대형봉제인형"처럼
   메인키워드 앞에 뭔가 끼워넣는 것 금지), 메인키워드 자체의 순서를 바꾸지 마.
2. 메인키워드 다음에는 반드시 띄어쓰기 하나를 넣고, 그 뒤에 서브키워드를 각각
   별도의 띄어쓰기로 구분된 단어로 나열해. 서브키워드를 메인키워드 뒤에 바로
   붙여서 새 복합명사를 만들지 마 (예: "봉제인형베개"처럼 붙이면 안 되고
   "봉제인형 베개"처럼 반드시 띄어써야 함).
3. 서브키워드는 4개를 기본으로 반드시 채워야 해 (서브 없이 메인키워드만 있는
   "봉제인형" 같은 출력은 금지). 4개를 넣으면 50자가 넘을 때만 3개, 그래도
   넘으면 2개로 줄이되, 그 경우에도 절대 0개는 안 됨. 서브키워드가 5개 이상인
   것도 스팸 판정이라 금지.
4. 전체 길이 50자는 반드시 지켜야 하는 최우선 규칙 — 서브키워드 개수를
   줄여서라도 50자를 넘기지 마. 글자를 중간에서 잘라내지 말고, 항상 완전한
   단어 단위로만 개수를 조절해.
5. 브랜드명 절대 포함 금지 (지재권 위험)
6. 각 상품명은 서로 다른 서브키워드 조합 (중복 금지) — 출력하기 전에 배열 안에 완전히
   똑같은 문자열이 두 개 이상 있는지 반드시 스스로 검토하고, 있으면 다른 조합으로 바꿔.
   상품 개수가 많아서 서브키워드 조합이 겹칠 것 같으면, 순서를 바꾸거나 다른 속성을
   골라서라도 전부 서로 달라야 해.
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
- "특대형봉제인형 방수 소재" (메인키워드 앞에 수식어가 붙어버림 - 메인키워드는 "봉제인형"인데
  "특대형"이 앞에 끼어들어감. "봉제인형 특대형 방수 소재"처럼 메인키워드 뒤에 와야 함)
- "봉제인형베개 특대형 소재 선물" (서브키워드 "베개"가 메인키워드에 바로 붙어서 새로운
  복합명사가 되어버림. "봉제인형 베개 특대형 소재"처럼 띄어써야 함)
- "봉제인형" (서브키워드가 하나도 없이 메인키워드만 있음)
- "낚시구명조끼 Decathlon 성인 부력" (브랜드명 포함)
- "낚시구명조끼 성인 부력 방수 배낚시 남성 안전 조끼 프로" (서브 너무 많음, 4개 초과)
- 메인키워드 자체가 길어서 서브 4개를 다 넣으면 50자를 넘는데도 그대로 4개를 강행하는 것 (이 경우 서브를 3개, 2개로 줄여서 반드시 50자를 지켜야 함)
- "낚시구명조끼 [최고급] 성인용" (특수문자)

아래는 실제 변환해야 할 중국어 원본 상품명 목록이야 (번호 순서대로). 각 제목에 담긴 실제 특징(재질/색상/사이즈/용도 등)을 참고해서 서브키워드를 뽑아줘. 일부 항목엔 괄호로 "(참고 상세속성: ...)"이 붙어있는데, 이건 상품 상세페이지에서 가져온 실제 스펙 정보라 제목보다 신뢰도가 높으니 적극 참고해줘. 원문/상세속성에 없는 특징은 지어내지 마.

{titles}

반드시 문자열만 담긴 JSON 배열로만 답해. 설명은 붙이지 말고, 상품 개수와 순서를 정확히 맞춰야 해.
"""


def generate_seo_titles(api_key: str, titles: list, keyword: str, attribute_contexts: list = None):
    """중국어 상품명 목록을 한국어 SEO 최적화 판매용 제목으로 일괄 변환한다.

    attribute_contexts: titles와 같은 순서/길이의 문자열 리스트(enrichWithDetails로 받은
    상세속성 요약). 있으면 제목만으로는 안 보이는 재질/기능 정보까지 참고해서 서브키워드를 뽑는다.
    """
    if not titles:
        return None, "변환할 상품이 없어요."

    lines = []
    for i, t in enumerate(titles):
        line = f"{i + 1}. {t}"
        if attribute_contexts and i < len(attribute_contexts) and attribute_contexts[i]:
            line += f" (참고 상세속성: {attribute_contexts[i]})"
        lines.append(line)
    numbered = "\n".join(lines)
    prompt = SEO_TITLE_PROMPT.format(keyword=keyword, titles=numbered)
    max_tokens = max(4096, 300 * len(titles))
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

    names = [str(t).strip()[:50] for t in result]
    names = _fix_bad_titles(api_key, names, titles, keyword)
    return names, None


FIX_SEO_TITLE_PROMPT = """방금 아래 상품들의 한국어 판매용 제목을 만들었는데, 문제가 있는 것들이 있어서
다시 만들어야 해 (형식이 틀렸거나, 다른 상품과 완전히 똑같은 이름이 나왔거나).

[규칙]
1. 메인키워드("{keyword}")를 절대 변형하지 말고 정확히 그 형태 그대로 맨 앞 단어로 써.
   메인키워드 앞에 다른 단어를 붙이거나("특대형봉제인형"처럼 앞에 끼워넣는 것 금지) 순서를 바꾸지 마.
2. 메인키워드 다음에 반드시 띄어쓰기 하나, 그 뒤에 서브키워드를 각각 띄어쓰기로 구분된
   별도 단어로 나열해. 서브키워드를 메인키워드에 바로 붙여서 새 복합명사를 만들지 마
   (예: "봉제인형베개"가 아니라 "봉제인형 베개").
3. 서브키워드는 4개를 기본으로 반드시 채워 (0개는 금지). 50자 넘으면 3개, 2개로 줄여도 되지만 0개는 안 됨.
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
    """메인키워드가 정확히 맨 앞 토큰이 아니거나, 서브키워드가 하나도 없으면 형식 오류로 본다."""
    parts = name.split()
    if not parts or parts[0] != keyword:
        return True
    return len(parts) < 2


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

        used_titles = "\n".join(sorted(seen)) if seen else "(없음)"
        numbered = "\n".join(f"{n + 1}. {original_titles[i]}" for n, i in enumerate(bad_indices))
        prompt = FIX_SEO_TITLE_PROMPT.format(keyword=keyword, used_titles=used_titles, titles=numbered)
        max_tokens = max(2048, 300 * len(bad_indices))
        text, error = _call_claude(api_key, prompt, max_tokens=max_tokens)
        if error:
            break
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            new_names = json.loads(text[start:end])
        except Exception:
            break
        if len(new_names) != len(bad_indices):
            break
        for idx, new_name in zip(bad_indices, new_names):
            names[idx] = str(new_name).strip()[:50]
    return names


def estimate_weights(api_key: str, titles: list):
    """titles 순서에 맞춰 무게(kg) 리스트를 추정해서 반환한다."""
    if not titles:
        return None, "추정할 상품이 없어요."

    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    prompt = WEIGHT_ESTIMATE_PROMPT.format(titles=numbered)
    max_tokens = max(4096, 300 * len(titles))
    text, error = _call_claude(api_key, prompt, max_tokens=max_tokens)
    if error:
        return None, error

    try:
        weight_by_n = _parse_weight_response(text)
    except Exception as e:
        return None, f"AI 응답을 숫자 목록으로 해석하지 못했어요 (응답이 도중에 잘렸을 수 있어요): {e}"

    missing = [i + 1 for i in range(len(titles)) if (i + 1) not in weight_by_n]
    if missing:
        # 큰 배치일수록 한두 개 누락이 흔해서, 누락된 상품만 따로 다시 물어봐서 채운다.
        retry_numbered = "\n".join(f"{n}. {titles[n - 1]}" for n in missing)
        retry_prompt = WEIGHT_ESTIMATE_PROMPT.format(titles=retry_numbered)
        retry_text, retry_error = _call_claude(api_key, retry_prompt, max_tokens=max(1024, 300 * len(missing)))
        if not retry_error:
            try:
                weight_by_n.update(_parse_weight_response(retry_text))
            except Exception:
                pass

    still_missing = [i + 1 for i in range(len(titles)) if (i + 1) not in weight_by_n]
    if still_missing:
        shown = still_missing[:10]
        more = f" 외 {len(still_missing) - 10}개" if len(still_missing) > 10 else ""
        return None, f"AI가 일부 상품(번호: {shown}{more})의 무게를 추정하지 못했어요. 다시 시도해보세요."

    return [weight_by_n[i + 1] for i in range(len(titles))], None
