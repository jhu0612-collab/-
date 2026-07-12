"""Claude API를 이용한 한국어 -> 중국어(간체) 키워드 번역."""

TRANSLATE_PROMPT_TEMPLATE = """다음 한국어 상품 키워드를 중국 이커머스(타오바오/1688)에서 실제로 검색에 쓰이는
중국어 간체 상품명 표현으로 바꿔줘. 글자 그대로의 직역이 아니라, 현지에서 그 상품을 부르는 실제 표현으로 바꿔줘.
번역된 중국어 단어만 출력하고, 다른 설명이나 따옴표는 붙이지 마.

키워드: {keyword}
"""


def translate_ko_to_zh(keyword: str, api_key: str):
    if not api_key:
        return None, "Anthropic API 키가 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not keyword or not keyword.strip():
        return None, "번역할 키워드가 비어있어요."

    try:
        import anthropic
    except ImportError:
        return None, "anthropic 패키지가 설치되지 않았어요. requirements.txt로 설치해주세요."

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=100,
            messages=[{"role": "user", "content": TRANSLATE_PROMPT_TEMPLATE.format(keyword=keyword)}],
        )
        return response.content[0].text.strip(), None
    except Exception as e:
        return None, f"번역 실패: {e}"
