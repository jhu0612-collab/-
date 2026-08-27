import json
import os

import streamlit as st

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KEYS_FILE = os.path.join(DATA_DIR, "api_keys.local.json")
KEY_NAMES = ["anthropic_api_key", "apify_api_token", "naver_client_id", "naver_client_secret"]


def _load_saved_keys():
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_keys(keys: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(KEYS_FILE, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=2)


def get_key(name, default=""):
    return st.session_state.get(name, default)


def set_key(name, value):
    st.session_state[name] = value


def render_api_key_sidebar():
    if not st.session_state.get("_keys_loaded"):
        saved = _load_saved_keys()
        for name in KEY_NAMES:
            if name in saved:
                st.session_state.setdefault(name, saved[name])
        st.session_state["_keys_loaded"] = True

    st.sidebar.header("API 키 설정")
    st.sidebar.caption("입력한 키는 이 컴퓨터에 자동 저장돼서, 프로그램을 껐다 켜도 다시 입력할 필요 없어요.")

    anthropic_key = st.sidebar.text_input(
        "Anthropic(Claude) API 키",
        value=get_key("anthropic_api_key"),
        type="password",
        help="console.anthropic.com 에서 발급",
    )
    apify_token = st.sidebar.text_input(
        "Apify API 토큰",
        value=get_key("apify_api_token"),
        type="password",
        help="apify.com 로그인 후 Settings > API & Integrations 에서 발급",
    )
    naver_client_id = st.sidebar.text_input(
        "네이버 API Client ID",
        value=get_key("naver_client_id"),
        type="password",
        help="developers.naver.com 에서 애플리케이션 등록 후 발급 (데이터랩/쇼핑검색 API 공용)",
    )
    naver_client_secret = st.sidebar.text_input(
        "네이버 API Client Secret",
        value=get_key("naver_client_secret"),
        type="password",
    )

    set_key("anthropic_api_key", anthropic_key)
    set_key("apify_api_token", apify_token)
    set_key("naver_client_id", naver_client_id)
    set_key("naver_client_secret", naver_client_secret)
    _save_keys(
        {
            "anthropic_api_key": anthropic_key,
            "apify_api_token": apify_token,
            "naver_client_id": naver_client_id,
            "naver_client_secret": naver_client_secret,
        }
    )

    if st.sidebar.button("저장된 키 삭제"):
        if os.path.exists(KEYS_FILE):
            os.remove(KEYS_FILE)
        for name in KEY_NAMES:
            st.session_state.pop(name, None)
        st.rerun()
