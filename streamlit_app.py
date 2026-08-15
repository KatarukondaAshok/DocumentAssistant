"""
streamlit_app.py
-----------------
Frontend for the Intelligent Document Assistant.
Talks to the FastAPI backend over REST using the `requests` library.

Run with:  streamlit run streamlit_app.py
Make sure the backend is running first (uvicorn app:app --port 8000).
"""
import streamlit as st
import requests

API_URL = "http://localhost:8000"

st.set_page_config(page_title="Intelligent Document Assistant", page_icon="📄", layout="wide")

# ---------------------------------------------------------------------------
# Session state initialization
# ---------------------------------------------------------------------------
for key, default in {
    "token": None,
    "username": None,
    "messages": [],
    "selected_doc_id": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def auth_headers():
    return {"Authorization": f"Bearer {st.session_state.token}"}


def api_post(path, json=None, files=None, data=None, auth=True):
    headers = auth_headers() if auth else {}
    return requests.post(f"{API_URL}{path}", json=json, files=files, data=data, headers=headers)


def api_get(path, auth=True):
    headers = auth_headers() if auth else {}
    return requests.get(f"{API_URL}{path}", headers=headers)


def api_delete(path, auth=True):
    headers = auth_headers() if auth else {}
    return requests.delete(f"{API_URL}{path}", headers=headers)


def safe_json(resp):
    """Parses a response as JSON; if the body isn't valid JSON (empty,
    HTML error page, server crash, etc.) this returns a readable error
    dict instead of raising and crashing the Streamlit app."""
    try:
        return resp.json()
    except ValueError:
        return {
            "detail": f"Backend returned a non-JSON response (HTTP {resp.status_code}). "
                      f"Raw response: {resp.text[:300] or '(empty body)'}"
        }


# ---------------------------------------------------------------------------
# LOGIN / SIGNUP SCREEN
# ---------------------------------------------------------------------------
def render_auth_screen():
    st.title("📄 Intelligent Document Assistant")
    st.caption("Login or create an account to start chatting with your documents.")

    tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

    with tab_login:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)
            if submitted:
                try:
                    resp = api_post("/login", json={"username": username, "password": password}, auth=False)
                    if resp.status_code == 200:
                        data = safe_json(resp)
                        st.session_state.token = data["access_token"]
                        st.session_state.username = data["username"]
                        st.rerun()
                    else:
                        st.error(safe_json(resp).get("detail", "Login failed"))
                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach the backend. Is it running on http://localhost:8000 ?")

    with tab_signup:
        with st.form("signup_form"):
            username = st.text_input("Choose a username")
            email = st.text_input("Email")
            password = st.text_input("Choose a password (min 6 chars)", type="password")
            submitted = st.form_submit_button("Create Account", use_container_width=True)
            if submitted:
                try:
                    resp = api_post(
                        "/signup", json={"username": username, "email": email, "password": password}, auth=False
                    )
                    if resp.status_code == 200:
                        data = safe_json(resp)
                        st.session_state.token = data["access_token"]
                        st.session_state.username = data["username"]
                        st.success("Account created! Redirecting...")
                        st.rerun()
                    else:
                        st.error(safe_json(resp).get("detail", "Signup failed"))
                except requests.exceptions.ConnectionError:
                    st.error("Cannot reach the backend. Is it running on http://localhost:8000 ?")


# ---------------------------------------------------------------------------
# MAIN APP (after login)
# ---------------------------------------------------------------------------
def render_sidebar():
    with st.sidebar:
        st.markdown(f"### 👋 Hello, {st.session_state.username}")
        if st.button("Logout", use_container_width=True):
            st.session_state.token = None
            st.session_state.username = None
            st.session_state.messages = []
            st.rerun()

        st.divider()
        st.subheader("📤 Upload a Document")
        uploaded_file = st.file_uploader("PDF, DOCX or TXT", type=["pdf", "docx", "txt"])
        if uploaded_file and st.button("Upload & Process", use_container_width=True):
            with st.spinner("Chunking, embedding, and indexing your document..."):
                files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                resp = api_post("/upload", files=files)
            if resp.status_code == 200:
                st.success(f"'{uploaded_file.name}' indexed successfully!")
                st.rerun()
            else:
                st.error(safe_json(resp).get("detail", "Upload failed"))

        st.divider()
        st.subheader("📚 Your Documents")
        docs_resp = api_get("/documents")
        docs = safe_json(docs_resp) if docs_resp.status_code == 200 else []

        options = {"All documents": None}
        for d in docs:
            options[d["filename"]] = d["id"]

        choice = st.selectbox("Chat scope", list(options.keys()))
        st.session_state.selected_doc_id = options[choice]

        for d in docs:
            col1, col2 = st.columns([4, 1])
            col1.caption(f"📄 {d['filename']}")
            if col2.button("🗑️", key=f"del_{d['id']}"):
                api_delete(f"/documents/{d['id']}")
                st.rerun()


def render_chat_tab():
    st.subheader("💬 Chat with your documents")

    mode = st.radio("Mode", ["Ask a question", "Summarize"], horizontal=True)

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    question = st.chat_input("Ask something about your document(s)...")
    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)

        payload = {
            "document_id": st.session_state.selected_doc_id,
            "question": question,
            "mode": "summarize" if mode == "Summarize" else "qa",
        }
        with st.spinner("Searching your documents..."):
            resp = api_post("/chat", json=payload)

        if resp.status_code == 200:
            data = safe_json(resp)
            answer = data["answer"]
            with st.chat_message("assistant"):
                st.write(answer)
                if data.get("sources"):
                    with st.expander("📎 Sources used"):
                        for s in data["sources"]:
                            st.caption(s)
            st.session_state.messages.append({"role": "assistant", "content": answer})
        else:
            st.error(safe_json(resp).get("detail", "Something went wrong"))


def render_history_tab():
    st.subheader("🕑 Conversation History")
    resp = api_get("/history")
    if resp.status_code != 200:
        st.error("Could not load history")
        return

    history = safe_json(resp)
    if not history:
        st.info("No conversations yet. Ask something in the Chat tab!")
        return

    for item in history:
        with st.container(border=True):
            st.markdown(f"**Q:** {item['question']}")
            st.markdown(f"**A:** {item['answer']}")
            st.caption(item["timestamp"])
            if st.button("Delete", key=f"hist_del_{item['id']}"):
                api_delete(f"/history/{item['id']}")
                st.rerun()


def render_main_app():
    render_sidebar()
    tab1, tab2 = st.tabs(["💬 Chat", "🕑 History"])
    with tab1:
        render_chat_tab()
    with tab2:
        render_history_tab()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
if st.session_state.token is None:
    render_auth_screen()
else:
    render_main_app()
