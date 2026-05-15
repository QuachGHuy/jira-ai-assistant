import streamlit as st
import requests
import uuid
import time
import os

# --- 1. CONFIGURATION & THEMING ---
BACKEND_URL = "http://backend:8000"

st.set_page_config(
    page_title="Jira AI Intelligence",
    page_icon="🤖",
    layout="wide"
)

# Custom CSS for professional "Jira-style" UI
st.markdown("""
    <style>
    /* Button styling: Neutral and professional colors */
    .stButton > button {
        width: 100%;
        border-radius: 6px;
        height: 3em;
        background-color: #F4F5F7;
        color: #42526E;
        border: 1px solid #DFE1E6;
        font-weight: 500;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background-color: #0052CC; /* Jira Blue */
        color: white;
        border-color: #0052CC;
    }
    /* Chat message area optimization */
    .stChatMessage {
        border-radius: 10px;
        padding: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 2. SESSION STATE INITIALIZATION ---
def init_session_state():
    """Initializes session variables if they don't exist."""
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "is_processing" not in st.session_state:
        st.session_state.is_processing = False

init_session_state()

# --- 3. HELPER FUNCTIONS ---
def send_sync_request(endpoint: str, label: str):
    """
    Sends a POST request to backend sync endpoints.
    Args:
        endpoint (str): API path.
        label (str): Human-readable name for notifications.
    """
    try:
        response = requests.post(f"{BACKEND_URL}{endpoint}")
        if response.status_code == 200:
            st.toast(f"✅ {label} successful!", icon="🎉")
        else:
            st.error(f"Failed to sync {label}: {response.status_code}")
    except Exception as e:
        st.error(f"Connection error: {e}")

# --- 4. HEADER & TOP ACTION BAR ---
st.title("🤖 Jira AI Intelligence Assistant")

# Action bar with cool-toned buttons
col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("📊 Sync Report"):
        send_sync_request("/api/v1/workflow/gsheet-report", "Report")

with col2:
    if st.button("🧠 Sync KB"):
        send_sync_request("/api/v1/sync/knowledge-base", "Knowledge Base")

with col3:
    if st.button("🔄 Sync Status"):
        send_sync_request("/api/v1/workflow/sync-status", "Ticket Status")

with col4:
    if st.button("🧹 Clear History"):
        # Reset chat and generate new thread_id for fresh memory
        st.session_state.messages = []
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.is_processing = False
        st.rerun()

st.divider()

# --- 5. CHAT INTERFACE ---
# Display historical chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# User Chat Input
# Disabled when st.session_state.is_processing is True to prevent double submission
if prompt := st.chat_input(
    "Ask me about Jira tickets or analytics...", 
    disabled=st.session_state.is_processing
):
    # Lock the interface
    st.session_state.is_processing = True
    
    # Add and display user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Process Assistant response
    with st.chat_message("assistant"):
        placeholder = st.empty()
        full_response = ""
        
        try:
            with st.spinner("Agent is analyzing..."):
                payload = {
                    "message": prompt, 
                    "session_id": st.session_state.session_id
                }
                response = requests.post(f"{BACKEND_URL}/api/v1/chat", json=payload, timeout=60)
                
                if response.status_code == 200:
                    raw_answer = response.json().get("reply", "I couldn't generate a response.")
                    
                    # Simulation of typing effect for better UX
                    for char in raw_answer:
                        full_response += char
                        placeholder.markdown(full_response + "▌")
                        time.sleep(0.003)
                    placeholder.markdown(full_response)
                    
                    # Record the final response
                    st.session_state.messages.append({"role": "assistant", "content": raw_answer})
                else:
                    st.error(f"Backend Error: {response.status_code}")
        except Exception as e:
            st.error(f"Communication error: {e}")
        finally:
            # Unlock the interface after processing (even if it failed)
            st.session_state.is_processing = False
            st.rerun() # Refresh to update input 'disabled' state

# --- 6. FOOTER ---
st.caption(f"Jira AI v1.5 | Thread: {st.session_state.session_id} | Status: Online")