import json
import os

import streamlit as st

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KEYS_FILE = os.path.join(DATA_DIR, "api_keys.local.json")
KEY_NAMES = ["eximbank_api_key", "anthropic_api_key", "apify_api_token"]


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

    eximbank_key = st.sidebar.text_input(
        "한국수출입은행 환율 API 키 (선택, 안 쓰면 환율 수동입력)",
        value=get_key("eximbank_api_key"),
        type="password",
        help="data.go.kr 또는 koreaexim.go.kr에서 무료 발급. 비워두면 마진계산기에서 환율을 직접 입력하면 돼요.",
    )
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

    set_key("eximbank_api_key", eximbank_key)
    set_key("anthropic_api_key", anthropic_key)
    set_key("apify_api_token", apify_token)
    _save_keys(
        {
            "eximbank_api_key": eximbank_key,
            "anthropic_api_key": anthropic_key,
            "apify_api_token": apify_token,
        }
    )

    if st.sidebar.button("저장된 키 삭제"):
        if os.path.exists(KEYS_FILE):
            os.remove(KEYS_FILE)
        for name in KEY_NAMES:
            st.session_state.pop(name, None)
        st.rerun()
