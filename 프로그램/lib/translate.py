"""네이버 파파고(NCP) API로 한국어 -> 중국어(간체) 번역."""

import requests

PAPAGO_URL = "https://naveropenapi.apigw.ntruss.com/nmt/v1/translation"


def translate_ko_to_zh(text: str, client_id: str, client_secret: str):
    if not client_id or not client_secret:
        return None, "파파고 API 키가 입력되지 않았어요. 사이드바에서 입력해주세요."
    if not text or not text.strip():
        return None, "번역할 텍스트가 비어있어요."

    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }
    data = {"source": "ko", "target": "zh-CN", "text": text}

    try:
        resp = requests.post(PAPAGO_URL, headers=headers, data=data, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        return result["message"]["result"]["translatedText"], None
    except Exception as e:
        return None, f"번역 API 호출 실패: {e}"
