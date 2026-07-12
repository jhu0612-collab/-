import streamlit as st


def get_key(name, default=""):
    return st.session_state.get(name, default)


def set_key(name, value):
    st.session_state[name] = value


def render_api_key_sidebar():
    st.sidebar.header("API 키 설정")
    st.sidebar.caption("여기 입력한 키는 저장되지 않고 이 화면을 켜둔 동안만 메모리에 유지돼요.")

    set_key(
        "eximbank_api_key",
        st.sidebar.text_input(
            "한국수출입은행 환율 API 키",
            value=get_key("eximbank_api_key"),
            type="password",
            help="data.go.kr 또는 koreaexim.go.kr에서 무료 발급",
        ),
    )
    set_key(
        "papago_client_id",
        st.sidebar.text_input(
            "네이버 파파고 Client ID",
            value=get_key("papago_client_id"),
            type="password",
        ),
    )
    set_key(
        "papago_client_secret",
        st.sidebar.text_input(
            "네이버 파파고 Client Secret",
            value=get_key("papago_client_secret"),
            type="password",
        ),
    )
    set_key(
        "anthropic_api_key",
        st.sidebar.text_input(
            "Anthropic(Claude) API 키",
            value=get_key("anthropic_api_key"),
            type="password",
            help="console.anthropic.com 에서 발급",
        ),
    )
