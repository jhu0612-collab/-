"""Claude API를 이용한 한국어<->중국어(간체) 키워드 번역."""

from lib.ai import _call_claude

KO_TO_ZH_PROMPT = """다음 한국어 상품 키워드를 중국 이커머스(타오바오/1688)에서 실제로 검색에 쓰이는
중국어 간체 상품명 표현으로 바꿔줘. 글자 그대로의 직역이 아니라, 현지에서 그 상품을 부르는 실제 표현으로 바꿔줘.
번역된 중국어 단어만 출력하고, 다른 설명이나 따옴표는 붙이지 마.

키워드: {keyword}
"""

ZH_TO_KO_PROMPT = """다음 중국어 상품 키워드를 한국에서 실제로 그 상품을 부를 때 쓰는 한국어 표현으로 바꿔줘.
반드시 띄어쓰기 없이 한 단어(복합명사)로 붙여서 써야 해 (예: "철근 결속기"가 아니라 "철근결속기").
이 키워드는 나중에 SEO 상품명 맨 앞에 그대로 들어가는 메인키워드로 쓰여서, 중간에 공백이 있으면
안 돼. 번역된 한국어 단어만 출력하고, 다른 설명이나 따옴표는 붙이지 마.

키워드: {keyword}
"""


def contains_hangul(text: str) -> bool:
    """문자열에 한글 음절이 하나라도 있으면 한국어로 간주한다."""
    return any("가" <= ch <= "힣" for ch in text or "")


def translate_ko_to_zh(keyword: str, api_key: str):
    if not keyword or not keyword.strip():
        return None, "번역할 키워드가 비어있어요."
    text, error = _call_claude(api_key, KO_TO_ZH_PROMPT.format(keyword=keyword), max_tokens=100)
    if error:
        return None, error
    return text.strip(), None


def translate_zh_to_ko(keyword: str, api_key: str):
    if not keyword or not keyword.strip():
        return None, "번역할 키워드가 비어있어요."
    text, error = _call_claude(api_key, ZH_TO_KO_PROMPT.format(keyword=keyword), max_tokens=100)
    if error:
        return None, error
    # 이 값이 나중에 SEO 상품명의 메인키워드로 그대로 쓰이는데, 중간에 공백이 있으면 안 되니
    # (프롬프트로 붙여쓰기를 지시해도 가끔 안 지켜질 수 있어서) 코드에서도 한 번 더 강제한다.
    result = text.strip().replace(" ", "")
    # AI가 가끔 번역을 안 하고 중국어 원문을 그대로 돌려주는 경우가 실제로 있었다(예:
    # "葱花切菜机" -> "葱花切菜机"). 이걸 그대로 두면 SEO 상품명이 "메인키워드"랍시고
    # 중국어로 시작해버리니, 한글이 하나도 없으면 번역 실패로 처리한다.
    if not contains_hangul(result):
        return None, f"AI가 한국어로 번역하지 못했어요(중국어를 그대로 반환함: '{result}'). 다시 시도해보세요."
    return result, None
